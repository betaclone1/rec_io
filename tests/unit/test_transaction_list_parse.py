"""Parse QBO TransactionList report Rows structure."""

from backend.bookkeeper.quickbooks.quickbooks_online_rest import (
    iter_transaction_list_data_rows,
    transaction_list_report_column_meta,
    transaction_list_report_headers,
    transaction_list_report_to_cell_rows,
    transaction_list_report_to_row_dicts,
)


def test_iter_transaction_list_nested_section() -> None:
    rows = {
        "Row": [
            {
                "type": "Section",
                "Header": {"ColData": [{"value": "Jan"}]},
                "Rows": {
                    "Row": [
                        {
                            "type": "Data",
                            "ColData": [
                                {"value": "2026-01-01"},
                                {"value": "Deposit"},
                            ],
                        }
                    ]
                },
            }
        ]
    }
    flat = iter_transaction_list_data_rows(rows)
    assert len(flat) == 1
    assert flat[0]["ColData"][0]["value"] == "2026-01-01"


def test_transaction_list_report_to_cell_rows() -> None:
    report = {
        "Columns": {
            "Column": [
                {"ColTitle": "Date"},
                {"ColTitle": "Amount"},
            ]
        },
        "Rows": {
            "Row": [
                {
                    "type": "Data",
                    "ColData": [{"value": "2026-01-02"}, {"value": "10.00"}],
                }
            ]
        },
    }
    hdrs, lines = transaction_list_report_to_cell_rows(report)
    assert transaction_list_report_headers(report) == ["Date", "Amount"]
    assert hdrs == ["Date", "Amount"]
    assert lines == [["2026-01-02", "10.00"]]


def test_transaction_list_posting_is_no_post_in_row_dicts() -> None:
    report = {
        "Columns": {
            "Column": [
                {"ColTitle": "Date", "ColType": "tx_date"},
                {"ColTitle": "Posting", "ColType": "is_no_post"},
            ]
        },
        "Rows": {
            "Row": [
                {
                    "type": "Data",
                    "ColData": [
                        {"value": "2026-05-04"},
                        {"value": "Yes", "is_no_post": False},
                    ],
                }
            ]
        },
    }
    titles, types = transaction_list_report_column_meta(report)
    assert titles == ["Date", "Posting"]
    assert types == ["tx_date", "is_no_post"]
    hdrs, col_types, row_dicts = transaction_list_report_to_row_dicts(report)
    assert hdrs == ["Date", "Posting"]
    assert col_types == ["tx_date", "is_no_post"]
    assert len(row_dicts) == 1
    assert row_dicts[0]["Date"] == "2026-05-04"
    assert row_dicts[0]["Posting"] == "Yes"
    assert row_dicts[0]["posting_is_no_post"] is False
