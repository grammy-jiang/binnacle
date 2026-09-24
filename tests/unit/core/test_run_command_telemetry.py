from binnacle.run_command_telemetry import (
    auto_background_policy_hash,
    auto_background_rule_hash,
)


def test_rule_hash_is_stable_and_scoped_by_prefix():
    assert auto_background_rule_hash("client", "rule") == auto_background_rule_hash(
        "client", "rule"
    )
    assert auto_background_rule_hash("client", "rule") != auto_background_rule_hash(
        "other", "rule"
    )


def test_policy_hash_covers_content_and_order():
    first = {"a": ("one", "two"), "b": ("three",)}
    same = {"a": ("one", "two"), "b": ("three",)}
    reordered = {"b": ("three",), "a": ("one", "two")}
    changed = {"a": ("one", "changed"), "b": ("three",)}
    assert auto_background_policy_hash(first) == auto_background_policy_hash(same)
    assert auto_background_policy_hash(first) != auto_background_policy_hash(reordered)
    assert auto_background_policy_hash(first) != auto_background_policy_hash(changed)
    assert len(auto_background_policy_hash({})) == 12
