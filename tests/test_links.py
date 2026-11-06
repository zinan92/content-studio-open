"""链接：存成公开链接；存不成的标出来；「已发出 → 链接」一处看全。"""
from __future__ import annotations

from content_studio import links


def test_backend_pages_become_public_links() -> None:
    assert links.public_url("youtube", "https://studio.youtube.com/video/X1y5HoaVV74/edit") == "https://www.youtube.com/watch?v=X1y5HoaVV74"
    assert links.public_url("douyin", "https://creator.douyin.com/creator-micro/work-management/work-detail/7690817035621666111?enter_from=content") \
        == "https://www.douyin.com/video/7690817035621666111"
    assert links.public_url("x", "https://x.com/example_user/status/1") == "https://x.com/example_user/status/1"
    assert "群发后" in links.issue("wechat_mp", "https://mp.weixin.qq.com/s?__biz=1&tempkey=abc")
    assert links.issue("wechat_mp", None) == "还没贴链接" and links.issue("miniprogram", None) is None


def test_post_ids_come_out_of_public_links() -> None:
    """概览的「内容 × 平台」表靠链接对上每个平台的帖子。"""
    assert links.post_id("bilibili", "https://www.bilibili.com/video/BV1qGan6qE2y") == "BV1qGan6qE2y"
    assert links.post_id("youtube", "https://www.youtube.com/watch?v=UWi_X3UI1K8") == "UWi_X3UI1K8"
    assert links.post_id("x", "https://x.com/example_user/status/2104238914576015810") == "2104238914576015810"
    assert links.post_id("xiaohongshu", "https://www.xiaohongshu.com/explore/6abb563c000000001a031df9?xsec_token=a") == "6abb563c000000001a031df9"
    assert links.post_id("wechat_mp", "https://mp.weixin.qq.com/s/abc") is None
