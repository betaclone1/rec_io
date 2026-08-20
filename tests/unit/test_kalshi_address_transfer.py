"""Kalshi address transfer routing: within-shard vs single IAT."""

from unittest.mock import MagicMock, patch

import pytest

from backend.bookkeeper.kalshi_subaccount_transfer import (
    apply_intra_exchange_instance_transfer,
    apply_subaccount_transfer,
    cents_to_centicents,
    transfer_kalshi_address,
)


def test_cents_to_centicents():
    assert cents_to_centicents(100) == 10000
    assert cents_to_centicents(1) == 100


@patch("backend.bookkeeper.kalshi_subaccount_transfer.kalshi_prod_request")
def test_apply_subaccount_transfer_includes_exchange_index(mock_req):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    mock_req.return_value = resp
    apply_subaccount_transfer("0001", 1, 0, 2500, "cid-1", exchange_index=2)
    assert mock_req.call_args[0][:3] == ("0001", "POST", "/portfolio/subaccounts/transfer")
    body = mock_req.call_args.kwargs["json_body"]
    assert body["exchange_index"] == 2
    assert body["from_subaccount"] == 1
    assert body["to_subaccount"] == 0
    assert body["amount_cents"] == 2500


@patch("backend.bookkeeper.kalshi_subaccount_transfer.kalshi_prod_request")
def test_apply_iat_includes_subaccounts_and_centicents(mock_req):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.content = b'{"transfer_id":"tid-1"}'
    resp.json.return_value = {"transfer_id": "tid-1"}
    mock_req.return_value = resp
    tid = apply_intra_exchange_instance_transfer(
        "0001",
        source_exchange_shard=0,
        destination_exchange_shard=2,
        source_subaccount=1,
        destination_subaccount=1,
        amount_cents=100,
    )
    assert tid == "tid-1"
    body = mock_req.call_args.kwargs["json_body"]
    assert body["amount"] == 10000
    assert body["source_exchange_shard"] == 0
    assert body["destination_exchange_shard"] == 2
    assert body["source_subaccount"] == 1
    assert body["destination_subaccount"] == 1


@patch("backend.bookkeeper.kalshi_subaccount_transfer.apply_subaccount_transfer")
def test_transfer_kalshi_address_same_shard(mock_xfer):
    out = transfer_kalshi_address(
        "0001",
        from_exchange=2,
        from_subaccount=1,
        to_exchange=2,
        to_subaccount=0,
        amount_cents=500,
        client_transfer_id="c1",
    )
    assert out["mode"] == "within_shard"
    mock_xfer.assert_called_once_with(
        "0001", 1, 0, 500, "c1", exchange_index=2
    )


@patch("backend.bookkeeper.kalshi_subaccount_transfer.wait_for_kalshi_address_credit")
@patch("backend.bookkeeper.kalshi_subaccount_transfer.apply_intra_exchange_instance_transfer")
@patch(
    "backend.bookkeeper.kalshi_portfolio_balance.fetch_subaccount_balances_matrix",
    return_value={1: {"balance_cents": 100, "exchange_balances_cents": {2: 100}}},
)
def test_transfer_kalshi_address_cross_shard_iat(mock_matrix, mock_iat, mock_wait):
    mock_iat.return_value = "tid-x"
    out = transfer_kalshi_address(
        "0001",
        from_exchange=0,
        from_subaccount=1,
        to_exchange=2,
        to_subaccount=1,
        amount_cents=100,
        client_transfer_id="c2",
        wait_for_iat_credit=True,
    )
    assert out["mode"] == "iat"
    assert out["transfer_id"] == "tid-x"
    mock_iat.assert_called_once()
    kwargs = mock_iat.call_args.kwargs
    assert kwargs["source_exchange_shard"] == 0
    assert kwargs["destination_exchange_shard"] == 2
    assert kwargs["source_subaccount"] == 1
    assert kwargs["destination_subaccount"] == 1
    assert kwargs["amount_cents"] == 100
    mock_wait.assert_called_once()


def test_apply_iat_rejects_same_shard():
    with pytest.raises(ValueError, match="different exchange shards"):
        apply_intra_exchange_instance_transfer(
            "0001",
            source_exchange_shard=0,
            destination_exchange_shard=0,
            source_subaccount=1,
            destination_subaccount=0,
            amount_cents=100,
        )
