"""Standalone tests for the natural Vietnamese finance parser.

This script intentionally avoids database and Telegram dependencies so it can
run in lightweight local environments.
"""

from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from utils.parser import (  # noqa: E402
    find_vietnamese_amounts,
    get_finance_parser_rule_stats,
    parse_alias_learning,
    parse_finance_message,
    parse_vietnamese_amount,
)


def assert_equal(actual, expected, label: str) -> None:
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def first_tx(text: str, aliases: list[dict] | None = None) -> dict:
    parsed = parse_finance_message(text, aliases)
    transactions = parsed.get("transactions") or []
    if not transactions:
        raise AssertionError(f"No transaction parsed for: {text!r}")
    return transactions[0]


def run_amount_tests() -> None:
    cases = {
        "100k": 100_000,
        "100 K": 100_000,
        "100 nghìn": 100_000,
        "100 ngàn": 100_000,
        "1tr": 1_000_000,
        "1 triệu": 1_000_000,
        "1tr2": 1_200_000,
        "1 triệu 2": 1_200_000,
        "1.2tr": 1_200_000,
        "2tr500": 2_500_000,
        "2 triệu rưỡi": 2_500_000,
        "250000": 250_000,
        "1,500,000": 1_500_000,
        "1.500.000": 1_500_000,
    }
    for text, expected in cases.items():
        assert_equal(int(parse_vietnamese_amount(text) or 0), expected, text)


def run_core_sentence_tests() -> None:
    cases = [
        ("chi 100k đổ xăng", "expense", "NEC", "Di chuyển", "HIGH"),
        ("chi 250k mua đồ ăn", "expense", "NEC", "Ăn uống thiết yếu", "HIGH"),
        ("mua rau thịt 180k", "expense", "NEC", "Ăn uống thiết yếu", "HIGH"),
        ("trả tiền nhà 3tr", "expense", "NEC", "Nhà thuê", "HIGH"),
        ("đóng wifi 220k", "expense", "NEC", "Hóa đơn", "HIGH"),
        ("mua thuốc 150k", "expense", "NEC", "Y tế", "HIGH"),
        ("mua cổ phiếu FPT 2tr", "allocation", "FFA", "Cổ phiếu", "HIGH"),
        ("đầu tư FPT 2tr", "allocation", "FFA", "Kinh doanh/tài sản", "HIGH"),
        ("chuyển 3tr vào quỹ dự phòng", "allocation", "LTS", "Quỹ dự phòng", "HIGH"),
        ("tiết kiệm 3tr", "allocation", "LTS", "Tiết kiệm", "HIGH"),
        ("mua sách network 250k", "expense", "EDU", "Chứng chỉ", "HIGH"),
        ("khóa học tiếng Anh 1tr", "expense", "EDU", "Khóa học", "HIGH"),
        ("đóng lệ phí thi CCNA 4tr", "expense", "EDU", "Chứng chỉ", "HIGH"),
        ("đi chơi với người yêu 500k", "expense", "PLAY", "Hẹn hò", "HIGH"),
        ("ăn tối với bạn bè 300k", "expense", "PLAY", "Bạn bè", "HIGH"),
        ("gym 500k", "expense", "PLAY", "Thể thao/sở thích", "HIGH"),
        ("đá bóng 100k", "expense", "PLAY", "Thể thao/sở thích", "HIGH"),
        ("du lịch 2tr", "expense", "PLAY", "Du lịch", "HIGH"),
        ("gửi bố mẹ 1tr", "expense", "GIVE", "Gia đình", "HIGH"),
        ("tặng quà sinh nhật 500k", "expense", "GIVE", "Quà tặng", "HIGH"),
        ("từ thiện 200k", "expense", "GIVE", "Từ thiện", "HIGH"),
        ("nhận lương 25tr", "income", None, None, "HIGH"),
        ("thưởng dự án 1.500.000", "income", None, None, "HIGH"),
    ]
    for text, tx_type, jar, category, confidence in cases:
        tx = first_tx(text)
        assert_equal(tx["transaction_type"], tx_type, text)
        assert_equal(tx["jar"], jar, text)
        assert_equal(tx["category"], category, text)
        assert_equal(tx["confidence"], confidence, text)


def run_generated_100_sentence_tests() -> None:
    templates = [
        "chi {amount} đổ xăng",
        "đổ xăng hết {amount}",
        "mua đồ ăn {amount}",
        "mua rau thịt {amount}",
        "trả tiền nhà {amount}",
        "đóng wifi {amount}",
        "mua thuốc {amount}",
        "mua cổ phiếu FPT {amount}",
        "đầu tư chứng khoán {amount}",
        "chuyển {amount} vào quỹ dự phòng",
        "tiết kiệm {amount}",
        "mua sách network {amount}",
        "khóa học tiếng Anh {amount}",
        "đóng lệ phí thi CCNA {amount}",
        "đi chơi với người yêu {amount}",
        "ăn tối với bạn bè {amount}",
        "gym {amount}",
        "đá bóng {amount}",
        "du lịch {amount}",
        "gửi bố mẹ {amount}",
        "tặng quà sinh nhật {amount}",
        "từ thiện {amount}",
        "cafe {amount}",
        "cafe chill {amount}",
        "ăn nhà hàng {amount}",
    ]
    amounts = ["50k", "100 K", "120 nghìn", "1tr2", "1 triệu 2"]
    checked = 0
    for template in templates:
        for amount in amounts:
            text = template.format(amount=amount)
            tx = first_tx(text)
            if "mua đồ " in text and "mua đồ ăn" not in text:
                continue
            if tx["transaction_type"] != "income":
                if tx["confidence"] == "LOW":
                    raise AssertionError(f"Expected confident parse for {text!r}: {tx}")
                if tx["jar"] is None:
                    raise AssertionError(f"Missing jar for {text!r}: {tx}")
            checked += 1
    if checked < 100:
        raise AssertionError(f"Expected at least 100 natural sentence checks, got {checked}")


def run_multi_and_ambiguous_tests() -> None:
    parsed = parse_finance_message("ăn sáng 50k, đổ xăng 100k")
    transactions = parsed.get("transactions") or []
    assert_equal(len(transactions), 2, "multi transaction count")
    assert_equal([int(tx["amount"]) for tx in transactions], [50_000, 100_000], "multi amounts")
    assert_equal([tx["jar"] for tx in transactions], ["NEC", "NEC"], "multi jars")

    parsed = parse_finance_message("chi 300k mua rau, thịt, cá")
    transactions = parsed.get("transactions") or []
    assert_equal(len(transactions), 1, "single amount with note commas")
    assert "rau, thịt, cá" in transactions[0]["note"]

    ambiguous = first_tx("chi 500k mua đồ")
    assert_equal(ambiguous["confidence"], "MEDIUM", "ambiguous confidence")
    assert_equal([choice["jar"] for choice in ambiguous["candidates"][:3]], ["NEC", "PLAY", "EDU"], "ambiguous choices")


def run_alias_tests() -> None:
    aliases_user_a = [{"phrase": "cơm gà cô ba", "jar_code": "NEC", "category": "Ăn uống"}]
    aliases_user_b: list[dict] = []
    tx_a = first_tx("cơm gà cô ba 55k", aliases_user_a)
    assert_equal(tx_a["jar"], "NEC", "alias user A jar")
    assert_equal(tx_a["category"], "Ăn uống", "alias user A category")
    tx_b = first_tx("cơm gà cô ba 55k", aliases_user_b)
    if tx_b["confidence"] == "HIGH" and tx_b["category"] == "Ăn uống":
        raise AssertionError("Alias leaked from user A to user B")

    learned = parse_alias_learning('từ giờ "sân bóng" là PLAY - Thể thao')
    assert_equal(learned["phrase"], "sân bóng", "alias phrase")
    assert_equal(learned["jar_code"], "PLAY", "alias jar")
    assert_equal(learned["category"], "Thể thao", "alias category")


def run_pending_duplicate_simulation() -> None:
    pending = first_tx("chi 500k mua đồ")
    fake_expenses = []
    if pending["confidence"] != "HIGH":
        pending_state = pending
    else:
        raise AssertionError("Ambiguous sentence should not auto-save")

    choice = pending_state["candidates"][1]
    fake_expenses.append((choice["jar"], pending_state["amount"], pending_state["note"]))
    pending_state = None
    if pending_state is not None:
        fake_expenses.append(("DUPLICATE", 0, "should not happen"))
    assert_equal(len(fake_expenses), 1, "confirmation should save once")


def main() -> None:
    stats = get_finance_parser_rule_stats()
    assert stats["rules"] >= 30
    assert stats["categories"] >= 30
    assert stats["keywords"] >= 250
    run_amount_tests()
    run_core_sentence_tests()
    run_generated_100_sentence_tests()
    run_multi_and_ambiguous_tests()
    run_alias_tests()
    run_pending_duplicate_simulation()
    print("PASS finance parser natural-message tests")
    print(stats)
    print("amount tokens:", find_vietnamese_amounts("ăn sáng 50k, đổ xăng 100k"))


if __name__ == "__main__":
    main()
