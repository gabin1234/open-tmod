import pytest

from tmod.ingestion import ingest, ingest_csv, normalize_header


def w(tmp_path, name, content, encoding="utf-8"):
    p = tmp_path / name
    p.write_bytes(content if isinstance(content, bytes) else content.encode(encoding))
    return p


def test_bom_and_header_normalization(tmp_path):
    p = w(tmp_path, "s.csv", "﻿ Ship Date ,Weight (lb),Origin ZIP\n2024-01-01,100,60601\n", "utf-8")
    t = ingest_csv(p)
    assert t.encoding == "utf-8-sig"
    assert t.columns == ("ship_date", "weight_lb", "origin_zip")
    assert t.raw_columns[0] == " Ship Date "
    assert t.rows[0]["ship_date"] == "2024-01-01"
    assert t.name == "s"


def test_cp949(tmp_path):
    p = w(tmp_path, "k.csv", "출발지,도착지\n서울,부산\n", "cp949")
    t = ingest_csv(p, "shipments")
    assert t.encoding == "cp949"
    assert t.columns == ("출발지", "도착지")
    assert t.rows[0]["출발지"] == "서울"
    assert t.issues == ()


def test_semicolon_delimiter(tmp_path):
    p = w(tmp_path, "s.csv", "a;b;c\n1;2;3\n4;5;6\n")
    t = ingest_csv(p)
    assert t.delimiter == ";"
    assert t.rows[1]["c"] == "6"


def test_ragged_rows_kept(tmp_path):
    p = w(tmp_path, "s.csv", "a,b,c\n1,2\n1,2,3,4\n")
    t = ingest_csv(p)
    assert len(t.rows) == 2
    assert t.rows[0]["c"] == ""
    assert t.rows[1]["c"] == "3"
    codes = [i.code for i in t.issues]
    assert codes == ["RAGGED_ROW", "RAGGED_ROW"]
    assert "'4'" in t.issues[1].detail


def test_blank_rows_skipped_and_row_numbers_physical(tmp_path):
    p = w(tmp_path, "s.csv", 'a,b\n1,"multi\nline"\n\n2,x\n')
    t = ingest_csv(p)
    assert [r["_row"] for r in t.rows] == [3, 5]
    assert t.rows[0]["b"] == "multi\nline"
    assert any(i.code == "BLANK_ROW" and i.row == 4 for i in t.issues)


def test_duplicate_and_empty_columns(tmp_path):
    p = w(tmp_path, "s.csv", "Zip,ZIP,zip,,---\n1,2,3,4,5\n")
    t = ingest_csv(p)
    assert t.columns == ("zip", "zip_2", "zip_3", "col_3", "col_4")
    assert t.rows[0]["zip_3"] == "3"
    assert [i.code for i in t.issues] == ["DUPLICATE_COLUMN", "DUPLICATE_COLUMN", "EMPTY_HEADER", "EMPTY_HEADER"]


def test_deterministic(tmp_path):
    p = w(tmp_path, "s.csv", "a,b\n1,2\n")
    assert ingest_csv(p) == ingest_csv(p)
    assert len(ingest_csv(p).sha256) == 64


def test_empty_file(tmp_path):
    p = w(tmp_path, "e.csv", "  \n")
    with pytest.raises(ValueError):
        ingest_csv(p)


def test_ingest_many(tmp_path):
    s = w(tmp_path, "x.csv", "a\n1\n")
    r = w(tmp_path, "y.csv", "b\n2\n")
    d = ingest({"shipments": s, "rates": r})
    assert set(d) == {"shipments", "rates"}
    assert d["rates"].name == "rates"


def test_normalize_header():
    assert normalize_header("  Weight (lb) ") == "weight_lb"
    assert normalize_header("__x__") == "x"
