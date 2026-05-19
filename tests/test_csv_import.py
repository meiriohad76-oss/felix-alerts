from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal
from uuid import uuid4

from sentinel_core.csv_import import import_portfolio_csv
from sentinel_core.models import PortfolioTickerView


class CsvImportTests(unittest.TestCase):
    def test_portfolio_ticker_model_defaults_to_investor(self):
        ticker = PortfolioTickerView(
            portfolio_id=uuid4(),
            portfolio_ticker_id=uuid4(),
            user_id=uuid4(),
            ticker="AAPL",
        )

        self.assertEqual(ticker.type, "investor")

    def test_ticker_only_import_creates_tickers(self):
        user_id = uuid4()
        portfolio_id = uuid4()
        report = import_portfolio_csv("ticker\nAAPL\nmsft\n", user_id=user_id, portfolio_id=portfolio_id)

        self.assertEqual(report.created_count, 2)
        self.assertEqual(report.rejected_count, 0)
        self.assertEqual([ticker.ticker for ticker in report.tickers], ["AAPL", "MSFT"])
        self.assertTrue(all(ticker.type == "investor" for ticker in report.tickers))

    def test_explicit_unknown_type_stays_unknown(self):
        user_id = uuid4()
        portfolio_id = uuid4()
        report = import_portfolio_csv(
            "ticker,type\nAAPL,unknown\n",
            user_id=user_id,
            portfolio_id=portfolio_id,
        )

        self.assertEqual(report.tickers[0].type, "unknown")

    def test_rich_import_parses_optional_fields(self):
        user_id = uuid4()
        portfolio_id = uuid4()
        csv_text = (
            "ticker,type,shares,entry_price,entry_date,current_profit_lock,notes\n"
            "PLUG,trader,1200,14.22,2025-08-11,12.50,Growth basket\n"
        )
        report = import_portfolio_csv(csv_text, user_id=user_id, portfolio_id=portfolio_id)
        ticker = report.tickers[0]

        self.assertEqual(ticker.ticker, "PLUG")
        self.assertEqual(ticker.type, "trader")
        self.assertEqual(str(ticker.shares), "1200")
        self.assertEqual(str(ticker.entry_price), "14.22")
        self.assertEqual(str(ticker.current_profit_lock), "12.50")

    def test_reupload_is_idempotent_for_tickers(self):
        user_id = uuid4()
        portfolio_id = uuid4()
        first = import_portfolio_csv("ticker\nAAPL\n", user_id=user_id, portfolio_id=portfolio_id)
        second = import_portfolio_csv(
            "ticker\nAAPL\n",
            user_id=user_id,
            portfolio_id=portfolio_id,
            existing=first.tickers,
        )

        self.assertEqual(second.created_count, 0)
        self.assertEqual(second.unchanged_count, 1)
        self.assertEqual(second.tickers[0].portfolio_ticker_id, first.tickers[0].portfolio_ticker_id)

    def test_duplicate_rows_are_rejected(self):
        user_id = uuid4()
        portfolio_id = uuid4()
        report = import_portfolio_csv("ticker\nAAPL\nAAPL\n", user_id=user_id, portfolio_id=portfolio_id)

        self.assertEqual(report.created_count, 1)
        self.assertEqual(report.rejected_count, 1)
        self.assertEqual(report.row_results[-1].issues[0].code, "duplicate_ticker")

    def test_ticker_only_merge_preserves_existing_setup_data(self):
        user_id = uuid4()
        portfolio_id = uuid4()
        existing = PortfolioTickerView(
            portfolio_id=portfolio_id,
            portfolio_ticker_id=uuid4(),
            user_id=user_id,
            ticker="AAPL",
            type="trader",
            entry_date=date(2026, 5, 1),
            shares=Decimal("12"),
            entry_price=Decimal("180.50"),
            current_profit_lock=Decimal("165.25"),
            user_exit_price=Decimal("160.00"),
            notes="User accepted protection setup",
        )

        report = import_portfolio_csv(
            "ticker\nAAPL\n",
            user_id=user_id,
            portfolio_id=portfolio_id,
            existing=(existing,),
        )

        ticker = report.tickers[0]
        self.assertEqual(report.unchanged_count, 1)
        self.assertEqual(ticker.type, "trader")
        self.assertEqual(ticker.entry_date, date(2026, 5, 1))
        self.assertEqual(ticker.shares, Decimal("12"))
        self.assertEqual(ticker.entry_price, Decimal("180.50"))
        self.assertEqual(ticker.current_profit_lock, Decimal("165.25"))
        self.assertEqual(ticker.user_exit_price, Decimal("160.00"))
        self.assertEqual(ticker.notes, "User accepted protection setup")

    def test_blank_merge_columns_preserve_existing_setup_data(self):
        user_id = uuid4()
        portfolio_id = uuid4()
        existing = PortfolioTickerView(
            portfolio_id=portfolio_id,
            portfolio_ticker_id=uuid4(),
            user_id=user_id,
            ticker="CGDV",
            type="investor",
            shares=Decimal("21"),
            entry_price=Decimal("37.80"),
            current_profit_lock=Decimal("34.20"),
            user_exit_price=Decimal("34.20"),
            notes="Protection saved in Sentinel",
        )

        report = import_portfolio_csv(
            "ticker,type,shares,entry_price,current_profit_lock,notes\nCGDV,,,,,\n",
            user_id=user_id,
            portfolio_id=portfolio_id,
            existing=(existing,),
        )

        ticker = report.tickers[0]
        self.assertEqual(report.unchanged_count, 1)
        self.assertEqual(ticker.shares, Decimal("21"))
        self.assertEqual(ticker.entry_price, Decimal("37.80"))
        self.assertEqual(ticker.current_profit_lock, Decimal("34.20"))
        self.assertEqual(ticker.user_exit_price, Decimal("34.20"))
        self.assertEqual(ticker.notes, "Protection saved in Sentinel")

    def test_explicit_merge_values_update_existing_setup_data(self):
        user_id = uuid4()
        portfolio_id = uuid4()
        existing = PortfolioTickerView(
            portfolio_id=portfolio_id,
            portfolio_ticker_id=uuid4(),
            user_id=user_id,
            ticker="AEM",
            type="investor",
            shares=Decimal("10"),
            entry_price=Decimal("70"),
            current_profit_lock=Decimal("64"),
            user_exit_price=Decimal("64"),
            notes="Old note",
        )

        report = import_portfolio_csv(
            "ticker,type,shares,entry_price,current_profit_lock,notes\nAEM,trader,15,75.50,69.25,Updated note\n",
            user_id=user_id,
            portfolio_id=portfolio_id,
            existing=(existing,),
        )

        ticker = report.tickers[0]
        self.assertEqual(report.updated_count, 1)
        self.assertEqual(ticker.type, "trader")
        self.assertEqual(ticker.shares, Decimal("15"))
        self.assertEqual(ticker.entry_price, Decimal("75.50"))
        self.assertEqual(ticker.current_profit_lock, Decimal("69.25"))
        self.assertEqual(ticker.user_exit_price, Decimal("69.25"))
        self.assertEqual(ticker.notes, "Updated note")

    def test_import_rejects_non_positive_numeric_values(self):
        user_id = uuid4()
        portfolio_id = uuid4()

        report = import_portfolio_csv(
            "ticker,shares,entry_price,current_profit_lock\n"
            "AAPL,0,110,95\n"
            "MSFT,5,0,280\n"
            "TSLA,2,250,-1\n",
            user_id=user_id,
            portfolio_id=portfolio_id,
        )

        self.assertEqual(report.created_count, 0)
        self.assertEqual(report.rejected_count, 3)
        self.assertEqual([row.issues[0].code for row in report.row_results], [
            "invalid_shares",
            "invalid_entry_price",
            "invalid_current_profit_lock",
        ])

    def test_import_rejects_non_finite_numeric_values(self):
        user_id = uuid4()
        portfolio_id = uuid4()

        report = import_portfolio_csv(
            "ticker,shares,entry_price,current_profit_lock\n"
            "AAPL,NaN,110,95\n"
            "MSFT,5,Infinity,280\n"
            "TSLA,2,250,-Infinity\n",
            user_id=user_id,
            portfolio_id=portfolio_id,
        )

        self.assertEqual(report.created_count, 0)
        self.assertEqual(report.rejected_count, 3)
        self.assertEqual([row.issues[0].code for row in report.row_results], [
            "invalid_shares",
            "invalid_entry_price",
            "invalid_current_profit_lock",
        ])


if __name__ == "__main__":
    unittest.main()
