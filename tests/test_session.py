"""Analysis session store, the three remaining MCP tools and the Task 1 hardening."""

import asyncio
import json

import pytest
from mcp import Client

from bist_harness.data import kap
from bist_harness.errors import DataUnavailableError
from bist_harness.harness import session
from bist_harness.mcp_server import server as srv
from bist_harness.storage import db
from bist_harness.tools import events as ev
from bist_harness.tools.indicators import add_all_indicators

from .synth import ohlcv


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(tmp_path / "test.sqlite")
    yield connection
    connection.close()


@pytest.fixture(autouse=True)
def offline_history(monkeypatch):
    frame = ohlcv(1200, 4)
    monkeypatch.setattr(srv, "load_history", lambda ticker: frame)
    return frame


def test_analysis_ids_are_unique_and_call_numbers_are_sequential():
    first = session.new_analysis("Is ASELS a buy?", model="qwen3")
    second = session.new_analysis("Is ASELS a buy?", model="qwen3")
    assert first.analysis_id != second.analysis_id
    assert first.snapshot_id == "test-snapshot" and first.adjustments_id
    a = session.record_call(
        first, state="TECHNICAL", tool="get_stock_history", arguments={}, output={}
    )
    b = session.record_call(
        first,
        state="TECHNICAL",
        tool="get_index_history",
        arguments={},
        output={"result_id": "r1"},
        allowed=False,
        source="harness",
    )
    assert (a.seq, b.seq) == (1, 2)
    assert (b.result_id, b.allowed, b.source) == ("r1", False, "harness")
    assert second.tool_calls == []


def test_saved_analysis_reads_back_equal(conn):
    analysis = session.new_analysis("Compare THYAO and PGSUS", model="qwen3")
    analysis.intent = {"ticker": "THYAO", "as_of": "2025-06-30"}
    analysis.state = "TECHNICAL"
    session.record_call(
        analysis,
        state="TECHNICAL",
        tool="get_stock_history",
        arguments={"ticker": "THYAO", "start": "2025-01-01", "end": "2025-06-30"},
        output={"rows": 5, "result_id": "abc", "note": "Türkçe"},
        source="harness",
    )
    session.save(analysis, conn)
    session.save(analysis, conn)  # saving again must replace, not duplicate
    assert session.load(analysis.analysis_id, conn) == analysis
    assert conn.execute("SELECT COUNT(*) FROM tool_calls").fetchone()[0] == 1


def test_loading_an_unknown_analysis_raises(conn):
    with pytest.raises(KeyError):
        session.load("nope", conn)


def test_quality_tool_reports_an_unknown_analysis_id():
    out = srv.check_data_quality("no-such-analysis")
    assert out["error"]["code"] == "UNKNOWN_ANALYSIS"
    assert srv.build_evidence_bundle("no-such-analysis")["error"]["code"] == "UNKNOWN_ANALYSIS"


def test_quality_tool_finds_a_live_analysis_that_was_never_saved():
    analysis = session.new_analysis("q", model="m")
    out = srv.get_stock_history("ASELS", "2021-01-01", "2021-12-31")
    session.record_call(
        analysis,
        state="S",
        tool="get_stock_history",
        arguments={"ticker": "ASELS", "start": "2021-01-01", "end": "2021-12-31"},
        output=out,
    )
    report = srv.check_data_quality(analysis.analysis_id)
    assert report["status"] == "PASS" and report["findings"] == []
    assert report["snapshot_id"] == "test-snapshot" and len(report["result_id"]) == 12


def test_quality_tool_collects_warnings_from_tool_outputs():
    analysis = session.new_analysis("q", model="m")
    session.record_call(
        analysis,
        state="S",
        tool="find_support_resistance",
        arguments={},
        output={
            "coverage_warning": "Requested period goes beyond the data.",
            "warnings": ["TOO_FEW_BARS: 20"],
        },
    )
    report = srv.check_data_quality(analysis.analysis_id)
    assert report["status"] == "PASS_WITH_WARNINGS"
    assert len(report["findings"]) == 2


def test_quality_tool_blocks_on_a_broken_series(monkeypatch, offline_history):
    broken = offline_history.copy()
    broken.iloc[100, broken.columns.get_loc("Close")] = -1.0
    monkeypatch.setattr(srv, "load_history", lambda ticker: broken)
    analysis = session.new_analysis("q", model="m")
    session.record_call(
        analysis,
        state="S",
        tool="get_stock_history",
        arguments={"ticker": "ASELS", "start": "2020-01-01", "end": "2021-12-31"},
        output={},
    )
    report = srv.check_data_quality(analysis.analysis_id)
    assert report["status"] == "HARD_BLOCK"
    assert any(
        f["code"] == "NON_POSITIVE_PRICE" and f["severity"] == "hard" for f in report["findings"]
    )


def test_speech_features_distinguish_empty_list_from_unknown_source(monkeypatch, tmp_path):
    monkeypatch.setattr(srv, "APPROVED_VIDEOS", tmp_path / "approved_videos.csv")
    assert srv.get_speech_features("v1")["error"]["code"] == "DATA_UNAVAILABLE"
    (tmp_path / "approved_videos.csv").write_text("source_id,title\nv1,Speech\n", encoding="utf-8")
    assert srv.get_speech_features("v2")["error"]["code"] == "UNKNOWN_SOURCE"


def test_evidence_bundle_is_not_implemented_yet():
    analysis = session.new_analysis("q", model="m")
    out = srv.build_evidence_bundle(analysis.analysis_id)
    assert out["error"]["code"] == "NOT_IMPLEMENTED"


def test_wrong_argument_type_is_invalid_over_mcp_and_directly():
    args = {
        "ticker": "ASELS",
        "start": "2021-01-01",
        "end": "2021-12-31",
        "event_type": "BOLLINGER_LOWER_TOUCH",
        "forward_days": "5",
        "direction": "BULLISH",
    }

    async def scenario():
        async with Client(srv.server) as client:
            return srv.unwrap_tool_result(await client.call_tool("detect_reversal_events", args))

    out = asyncio.run(scenario())
    assert out["error"]["code"] == "INVALID_ARGUMENT"
    assert "forward_days" in out["error"]["message"]
    assert srv.detect_reversal_events(**args)["error"]["code"] == "INVALID_ARGUMENT"


def test_valid_call_over_mcp_still_works_after_the_strict_wrapper():
    async def scenario():
        async with Client(srv.server) as client:
            result = await client.call_tool(
                "detect_reversal_events",
                {
                    "ticker": "ASELS",
                    "start": "2021-01-01",
                    "end": "2021-12-31",
                    "event_type": "BOLLINGER_LOWER_TOUCH",
                    "forward_days": 5,
                },
            )
            return srv.unwrap_tool_result(result)

    out = asyncio.run(scenario())
    assert "error" not in out and out["forward_days"] == 5


def test_event_records_can_be_written_as_strict_json():
    df = add_all_indicators(ohlcv(600, 2))
    mask = ev.event_mask(df, "RSI_LOCAL_TROUGH")
    mask.iloc[:16] = False
    mask.iloc[-3:] = True  # the last days have no forward return yet
    records = ev.event_records(
        df, mask, ticker="ASELS", event_type="RSI_LOCAL_TROUGH", direction="BULLISH"
    )
    text = json.dumps(records.to_dict("records"), allow_nan=False)
    assert "NaN" not in text and "null" in text


def test_kap_build_raises_when_a_member_id_is_missing(tmp_path):
    with pytest.raises(DataUnavailableError, match="member id"):
        kap.build_kap(
            tmp_path / "s1",
            ["TUPRS"],
            start="2025-01-01",
            end="2025-12-31",
            get_json=lambda url, params: [],
            post_json=lambda url, body: [],
            pause=0,
            sleep=lambda s: None,
        )


def test_feature_table_cache_is_keyed_by_the_layer_identity(monkeypatch):
    from bist_harness.features import table as ft

    ft.clear_feature_cache()
    history = ohlcv(300, 3)
    built = []
    real = ft._build_feature_table

    def counting(*args, **kwargs):
        built.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(ft, "_build_feature_table", counting)
    ids = {"snapshot": "s1", "adjustments": "a1", "layers": "l1"}
    monkeypatch.setattr(ft, "_cache_identity", lambda: dict(ids))
    kwargs = {"peer_closes": {"ASELS": history["Close"]}, "benchmark": history["Close"]}
    first = ft.build_feature_table("ASELS", history, **kwargs)
    second = ft.build_feature_table("ASELS", history, **kwargs)
    assert len(built) == 1 and first.equals(second)
    ids["layers"] = "l2"  # a rebuilt layer must not return stale features
    ft.build_feature_table("ASELS", history, **kwargs)
    assert len(built) == 2
    ft.build_feature_table("ASELS", history.iloc[:-5], **kwargs)  # other arguments
    assert len(built) == 3


def test_quality_tool_resolves_an_analysis_saved_by_an_earlier_process(monkeypatch, tmp_path):
    path = tmp_path / "store.sqlite"
    monkeypatch.setattr(session, "_store_path", lambda: path)
    analysis = session.new_analysis("q", model="m")
    connection = db.connect(path)
    session.save(analysis, connection)
    connection.close()
    session._LIVE.clear()  # a new process knows nothing live
    assert srv.check_data_quality(analysis.analysis_id)["status"] == "PASS"
    assert srv.check_data_quality("still-unknown")["error"]["code"] == "UNKNOWN_ANALYSIS"


def test_a_missing_store_file_is_not_created_by_the_lookup(monkeypatch, tmp_path):
    path = tmp_path / "none" / "store.sqlite"
    monkeypatch.setattr(session, "_store_path", lambda: path)
    assert srv.check_data_quality("x")["error"]["code"] == "UNKNOWN_ANALYSIS"
    assert not path.exists()


def test_feature_table_without_a_snapshot_bypasses_the_cache(monkeypatch):
    from bist_harness.features import table as ft

    def no_snapshot():
        raise DataUnavailableError("no snapshot")

    monkeypatch.setattr(ft, "_identity_parts", no_snapshot)
    ft.clear_feature_cache()
    history = ohlcv(300, 3)
    kwargs = {"peer_closes": {"ASELS": history["Close"]}, "benchmark": history["Close"]}
    assert len(ft.build_feature_table("ASELS", history, **kwargs)) == 300
    assert not ft._CACHE


def test_feature_table_cache_is_bounded_and_shared_frames_hash_once(monkeypatch):
    from bist_harness.features import table as ft

    ft.clear_feature_cache()
    monkeypatch.setattr(ft, "_cache_identity", lambda: {"snapshot": "s"})
    monkeypatch.setattr(ft, "_build_feature_table", lambda t, h, **k: h.copy())
    monkeypatch.setattr(ft, "CACHE_LIMIT", 3)
    history = ohlcv(100, 3)
    hashed = []
    real = ft._hash_frame
    monkeypatch.setattr(ft, "_hash_frame", lambda f: hashed.append(1) or real(f))
    shared = ohlcv(100, 5)
    for n in range(6):
        ft.build_feature_table(f"T{n}", history, disclosures=shared)
    assert len(ft._CACHE) == 3
    assert len(hashed) == 2  # history and the shared frame, once each
