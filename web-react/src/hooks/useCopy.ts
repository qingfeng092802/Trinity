import { App } from 'antd';
import { useCallback } from 'react';

import { copyText } from '../utils/format';

/** 复制，并且**一定**给得出结果。
 *
 * 要解决的原始问题：`copyText` 在不安全上下文（http 访问）、用户拒绝权限、
 * 浏览器禁写剪贴板时返回 false，而调用方是 `if (!ok) return` —— 静默吞掉。
 * 用户点完只看到「什么都没发生」，分不清是没点到按钮、还是没权限，
 * 更不知道下一步该手动选中复制。所以失败必须有话说清楚的去路。
 *
 * 成功不一定需要 Toast：CopyButton 自己有 1.6s 的对勾态（就在手指刚点的位置）。
 * 只有那种「按钮点了不会变样」的场景（例如数据源体检弹层里的修复命令）才补一句
 * `okMessage`，否则每次复制都弹一条，Toast 就成了噪音。
 */
export function useCopy(): (text: string, opts?: { okMessage?: string }) => Promise<boolean> {
  const { message } = App.useApp();

  return useCallback(
    async (text: string, opts?: { okMessage?: string }) => {
      const ok = await copyText(text);
      if (ok) {
        if (opts?.okMessage) message.success(opts.okMessage);
      } else {
        message.error('复制失败：浏览器拒绝了剪贴板写入（常见于 http 访问或未授予权限），请手动选中后复制', 5);
      }
      return ok;
    },
    [message],
  );
}
