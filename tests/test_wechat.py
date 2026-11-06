

def test_ip_whitelist_error_names_the_ip_wechat_saw() -> None:
    from content_studio.extras.autopost import wechat

    reason, note = wechat.explain({"errcode": 40164, "errmsg": "invalid ip 154.31.115.43 ipv6 ::ffff:154.31.115.43, not in whitelist rid: x"})
    assert reason == "ip" and "154.31.115.43" in note and "IP 白名单" in note
