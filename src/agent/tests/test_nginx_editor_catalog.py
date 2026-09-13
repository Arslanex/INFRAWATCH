"""Insert menu respects nginx structure — not everything goes everywhere."""
from iw_agent.modules.nginx.confparse import parse
from iw_agent.modules.nginx.editor.catalog import options_for_insert


def _server_block():
    doc = parse(
        "server {\n"
        "    listen 80;\n"
        "    server_name demo.test;\n"
        "    location / { proxy_pass http://127.0.0.1:1; }\n"
        "}\n"
    )
    return doc, doc.children[0]


def test_file_root_cannot_add_server_blocks():
    doc = parse("server { listen 80; }\n")
    labels = [option.label for option in options_for_insert(doc, len(doc.children))]
    assert "comment" in labels
    assert not any("server block" in label for label in labels)


def test_after_listen_offers_port_options_only():
    doc, server = _server_block()
    labels = [option.label for option in options_for_insert(server, 1)]
    assert any("listen" in label for label in labels)
    assert not any(label.startswith("location") for label in labels)


def test_after_server_name_offers_locations():
    doc, server = _server_block()
    labels = [option.label for option in options_for_insert(server, 2)]
    assert any("location" in label for label in labels)


def test_location_block_offers_proxy_not_listen():
    from pathlib import Path

    from iw_agent.modules.nginx.confparse import Block

    text = Path(__file__).parent.joinpath("fixtures", "nginx", "simple_proxy.conf").read_text()
    doc = parse(text)
    location = next(
        node for node in doc.walk() if isinstance(node, Block) and node.name == "location"
    )
    labels = [option.label for option in options_for_insert(location, len(location.children))]
    assert "proxy_pass" in labels
    assert not any("listen" in label for label in labels)
