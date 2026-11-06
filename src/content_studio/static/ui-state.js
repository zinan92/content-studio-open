'use strict';
/* Shared presentation only: never infer a business success from a request result. */
const WorkbenchUI = {
  createWorkOrigins() {
    const origins = new Map();
    const labels = { today: '盘', input: '找', radar: '老师和对标名单', report: '拆解报告', board: '正在做的', platform: '平台', plats: '各平台', mine: '作品分析', swipe: '流量视频' };
    return {
      capture(id, context) {
        if (!context || ['work', 'pack'].includes(context.view)) return;
        origins.set(String(id), { view: context.view, hash: context.hash || '#' + context.view, scrollY: Math.max(0, Number(context.scrollY) || 0) });
      },
      get(id) { return origins.get(String(id)) || { view: 'board', hash: '#board', scrollY: 0 }; },
      label(id) { return labels[this.get(id).view] || '返回来源'; },
    };
  },
  failureHint(error) {
    const raw = String(error || '');
    if (/cookie|login|登录|凭据|401|403/i.test(raw)) return '登录状态可能已过期。先检查平台连接，再重试。';
    if (/private|removed|restricted|视频不存在|已删除|API refused/i.test(raw)) return '暂时无法读取这条视频。先打开原链接，确认视频仍可访问，再重试。';
    if (/timeout|timed out|超时|network|连接/i.test(raw)) return '连接超时或网络暂时不可用。检查网络后重试。';
    if (/disk|space|磁盘|空间/i.test(raw)) return '本机存储空间不足。腾出空间后重试。';
    if (/download|下载/i.test(raw)) return '视频下载未完成。先确认原视频可打开，再重试。';
    return '这次处理没有完成。展开错误详情查看原因，处理后可重试。';
  },
};
if (typeof window !== 'undefined') window.WorkbenchUI = WorkbenchUI;
if (typeof module !== 'undefined') module.exports = WorkbenchUI;
