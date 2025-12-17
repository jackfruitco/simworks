import pytest

from orchestrai.identity import Identity, IdentityResolver


def test_domain_precedence_and_normalization_default_context():
    class Demo:
        namespace = "DemoSpace"
        group = "Group"
        name = "ExplicitName"

    ident, meta = IdentityResolver().resolve(Demo, context={"default_domain": "SIM.Core"})

    assert ident.domain == "sim-core"
    assert meta["simcore.identity.source.domain"] == "default"
    assert ident.namespace == "demo_space"
    assert ident.group == "group"
    assert ident.name == "ExplicitName"
    assert meta["simcore.tuple4.post_norm"] == ident.as_str


@pytest.mark.parametrize(
    "domain_arg, domain_attr, expected, source",
    [
        ("Explicit", "AttrDomain", "explicit", "arg"),
        (None, "AttrDomain", "attrdomain", "attr"),
    ],
)
def test_domain_arg_overrides_and_attr_precedence(domain_arg, domain_attr, expected, source):
    class Demo:
        domain = domain_attr
        namespace = "demo"
        group = "demo"

    ident, meta = IdentityResolver().resolve(Demo, domain=domain_arg)

    assert ident.domain == expected
    assert meta["simcore.identity.source.domain"] == source


def test_resolve_facade_tuple_helpers_are_four_part_only():
    ident = Identity(domain="d", namespace="n", group="g", name="x")

    assert Identity.resolve.as_tuple(ident) == ("d", "n", "g", "x")
    assert Identity.resolve.as_tuple4(ident) == ("d", "n", "g", "x")
    assert Identity.resolve.as_label(ident) == "d.n.g.x"
