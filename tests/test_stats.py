import math

from evaluation.stats import mcnemar_exact, wilson_ci


class TestWilsonCI:
    def test_textbook_value(self) -> None:
        lo, hi = wilson_ci(101, 112)
        assert abs(lo - 0.8331) < 0.001
        assert abs(hi - 0.9438) < 0.001

    def test_perfect_score_upper_is_one(self) -> None:
        lo, hi = wilson_ci(112, 112)
        assert hi == 1.0
        assert 0.96 < lo < 0.97

    def test_zero_score_lower_is_zero(self) -> None:
        lo, hi = wilson_ci(0, 112)
        assert lo < 1e-12
        assert hi < 0.04

    def test_empty_n(self) -> None:
        assert wilson_ci(0, 0) == (0.0, 1.0)

    def test_bounds_ordering(self) -> None:
        for k in range(0, 113, 7):
            lo, hi = wilson_ci(k, 112)
            assert 0.0 <= lo <= k / 112 + 1e-12
            assert k / 112 - 1e-12 <= hi <= 1.0


class TestMcNemarExact:
    def test_no_discordance(self) -> None:
        assert mcnemar_exact(0, 0) == 1.0

    def test_one_sided_flip(self) -> None:
        assert math.isclose(mcnemar_exact(0, 8), 2 / 256)
        assert math.isclose(mcnemar_exact(8, 0), 2 / 256)

    def test_headline_pair(self) -> None:
        assert math.isclose(mcnemar_exact(1, 10), 2 * 12 / 2048)

    def test_balanced_is_one(self) -> None:
        assert mcnemar_exact(5, 5) == 1.0

    def test_capped_at_one(self) -> None:
        assert mcnemar_exact(4, 5) <= 1.0
