import csv
import json

from arbitrage import cli
from arbitrage.models import Offer


class FakeMarket:
    name = "naver"

    def search(self, query, limit):
        return [
            Offer("naver", "Silicone kitchen tongs set", 12_900, "KRW", "https://n/1", cross_border=False),
            Offer("naver", "실리콘 주방 집게", 13_500, "KRW", "https://n/2", cross_border=False),
        ]


def test_price_command(capsys):
    code = cli.main(["price", "--cost", "5", "--currency", "USD", "--shipping", "1", "--market-price", "19900", "--offline-fx"])
    out = capsys.readouterr().out
    assert code == 0
    assert "landed cost: ₩8,436" in out  # 6 USD x 1365 x 1.03
    assert "naver" in out and "coupang" in out
    assert "at ₩19,900" in out


def test_scan_with_csv_supplier(monkeypatch, tmp_path, fixtures_dir, capsys):
    monkeypatch.setattr(cli, "build_market", FakeMarket)
    out_csv = tmp_path / "report.csv"
    code = cli.main([
        "scan", "tongs", "--source", f"csv:{fixtures_dir / 'suppliers.csv'}",
        "--no-images", "--offline-fx", "--out", str(out_csv), "--sell-on", "naver",
    ])
    out = capsys.readouterr().out
    assert code == 0
    assert "2 supplier products checked, 2 found on naver" in out
    rows = list(csv.DictReader(out_csv.open(encoding="utf-8-sig")))
    assert {r["source_platform"] for r in rows} == {"temu", "domeggook"}
    assert all(r["market_low_krw"] for r in rows)
    assert "naver_profit" in rows[0] and "coupang_profit" not in rows[0]


def test_temu_source_explains_why(capsys):
    assert cli.main(["scan", "x", "--source", "temu", "--offline-fx"]) == 2
    assert "forbid scraping" in capsys.readouterr().err


def test_unknown_marketplace(capsys):
    assert cli.main(["price", "--cost", "1000", "--sell-on", "amazon"]) == 2
    assert "--sell-on accepts" in capsys.readouterr().err


def test_scan_json_matches_documented_contract(monkeypatch, tmp_path, fixtures_dir):
    monkeypatch.setattr(cli, "build_market", FakeMarket)
    out_json = tmp_path / "scan.json"
    code = cli.main([
        "scan", "tongs", "--source", f"csv:{fixtures_dir / 'suppliers.csv'}", "--no-images", "--offline-fx",
        "--out", str(tmp_path / "r.csv"), "--json", str(out_json),
    ])
    assert code == 0
    data = json.loads(out_json.read_text("utf-8"))
    assert data["schema_version"] == 1
    assert data["query"] == "tongs" and data["source_count"] == 2
    assert set(data["fee_rates"]) == {"naver", "coupang"}
    opp = data["opportunities"][0]
    assert set(opp) == {"id", "source", "landed_cost", "market_low", "best_marketplace", "quotes", "matches", "notes", "compliance"}
    assert data["dropped"] == []
    assert opp["id"].startswith(opp["source"]["platform"] + ":")
    assert set(opp["quotes"]["naver"]) == {"marketplace", "list_price", "break_even", "min_viable", "profit", "margin", "viable"}
    assert {"offer", "score", "reasons"} == set(opp["matches"][0])


def test_scan_warns_when_supplier_photos_are_not_compared(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "build_market", FakeMarket)
    csv_path = tmp_path / "temu.csv"
    csv_path.write_text(
        "platform,title,price,currency,url,image_url\n"
        "temu,Silicone kitchen tongs set,3.20,USD,https://temu/1,https://img/1.jpg\n",
        encoding="utf-8",
    )
    code = cli.main(["scan", "tongs", "--source", f"csv:{csv_path}", "--no-images", "--offline-fx", "--out", str(tmp_path / "r.csv")])
    assert code == 0
    err = capsys.readouterr().err
    assert "1 supplier products have photos but they were not compared" in err
    assert "--no-images" in err


def test_scan_accepts_a_glossary_csv(monkeypatch, tmp_path, capsys):
    class KoreanMarket:
        name = "naver"

        def search(self, query, limit):
            return [Offer("naver", "프로브니케이터 FB-2000X 정품", 15_900, "KRW", "https://n/1", cross_border=False)]

    monkeypatch.setattr(cli, "build_market", KoreanMarket)
    monkeypatch.setattr(cli.ImageHasher, "available", staticmethod(lambda: False))
    csv_path = tmp_path / "temu.csv"
    csv_path.write_text("title,price,currency,url,model\nFrobnicator,3.20,USD,https://temu/1,FB-2000X\n", encoding="utf-8")
    glossary = tmp_path / "g.csv"
    glossary.write_text("frobnicator,프로브니케이터\n", encoding="utf-8")
    argv = ["scan", "x", "--source", f"csv:{csv_path}", "--offline-fx", "--out", str(tmp_path / "r.csv")]
    # The shared model code alone (0.5) is just under the threshold; the glossary adds the title signal.
    assert cli.main(argv) == 0
    assert "1 supplier products checked, 0 found on naver" in capsys.readouterr().out
    assert cli.main(argv + ["--glossary", str(glossary)]) == 0
    assert "1 supplier products checked, 1 found on naver" in capsys.readouterr().out
