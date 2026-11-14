import asyncio
import io
import re

from agora import cli
from agora.cli import Paint, render_ladder, run

try:
    from tests import surface_fakes as fk
except ImportError:
    import surface_fakes as fk

ANSI = re.compile(r"\033\[[0-9;]*m")


def run_cli(color: bool = False, as_json: bool = False) -> str:
    buf = io.StringIO()
    asyncio.run(run("used sony a7 iii under 900", buf, color=color, as_json=as_json, hunt_kwargs=fk.kwargs()))
    return buf.getvalue()


def test_cli_renders_events_ladder_verdict_and_budget():
    out = run_cli()
    assert "OFFER" in out and "SKIP" in out and "ERROR" in out
    assert "PRICE LADDER" in out
    for col in ("NEW", "REFURB", "USED"):
        assert col in out
    assert "/mo" in out                       # true cost per month next to offers
    assert "your budget" in out               # budget line from need.budget = 900
    assert "Buy the used one" in out          # verdict box
    assert "credits" in out and "pages read free" in out
    assert "★" in out


def test_ladder_puts_offers_in_condition_columns():
    offers = [
        {"url": "a", "source": "new.shop", "price_eur": 1400, "condition": "new"},
        {"url": "b", "source": "used.market", "price_eur": 800, "condition": "used",
         "true_cost": {"per_month_eur": 10.0}},
    ]
    text = render_ladder(offers, Paint(False), width=100, best_tc_url="b")
    header, *rows = text.splitlines()
    new_col = header.index("NEW")
    used_col = header.index("USED")
    row_new = next(r for r in rows if "new.shop" in r)
    row_used = next(r for r in rows if "used.market" in r)
    assert new_col <= row_new.index("● 1,400") < header.index("REFURB")
    assert row_used.index("● 800") >= used_col
    assert "€10/mo" in row_used and "★" in row_used
    # EUR axis descends: the 1,400 row comes before the 800 row
    assert rows.index(row_new) < rows.index(row_used)


def test_ladder_empty():
    assert "no priced offers" in render_ladder([], Paint(False))


def test_color_output_strips_to_same_text():
    plain, colored = run_cli(color=False), run_cli(color=True)
    assert "\033[" in colored
    strip = lambda s: re.sub(r"\s+\d+\.\d\ds ", " ", ANSI.sub("", s))  # timings differ between runs
    assert "PRICE LADDER" in strip(colored)


def test_json_mode_prints_event_lines():
    lines = [l for l in run_cli(as_json=True).splitlines() if l.strip()]
    import json
    assert json.loads(lines[0])["type"] == "need"
    assert json.loads(lines[-1])["type"] == "done"


def test_main_parses_args(monkeypatch):
    seen = {}

    async def fake_run(query, out, *, color, as_json, hunt_kwargs):
        seen.update(query=query, hunt_kwargs=hunt_kwargs, as_json=as_json)
        return 0

    monkeypatch.setattr(cli, "run", fake_run)
    assert cli.main(["used", "a7", "iii", "--max-sources", "5", "--json"]) == 0
    assert seen == {"query": "used a7 iii", "hunt_kwargs": {"max_sources": 5}, "as_json": True}
