import { Component } from 'react';
import type { ErrorInfo, ReactNode } from 'react';
import { Button } from 'antd';

import { truncate } from '../utils/format';

interface Props {
  children: ReactNode;
  /** 出错位置的名字；只进次级文案，主文案固定一句 */
  label?: string;
}

type State = { error: Error | null };

/** 动态 import 失败的错误签名（各家浏览器的措辞不一样，都收在这里）。
 *  路由级拆包之后这是一类**新**的失败：产物重新构建过、旧标签页里的 hash 已经 404。 */
const CHUNK_LOAD_FAILED =
  /dynamically imported module|Importing a module script failed|error loading dynamically imported module|could not load\b/i;

/** 这一类错误点「重试」是**骗人**的：React.lazy 把 promise（含已 rejected 的那一枚）
 *  缓在组件上，清掉 error 状态再渲染一次走的还是同一个 rejected promise，不会再发请求。
 *  唯一真能恢复的动作是重新加载文档 —— 那才会重新取 index.html 里那批新 hash。 */
function isChunkLoadFailure(error: Error): boolean {
  return CHUNK_LOAD_FAILED.test(error.message || String(error));
}

/** 渲染崩溃的局部兜底。
 *
 * React 里没有错误边界时，任何一次 render 抛错会卸载**整棵树** —— 症状就是白屏，
 * 用户只剩「刷新」这一条路。这里给右侧主内容区（整页）和每个页签（局部）各包一层：
 * 少渲染一块，好过整页不见。
 *
 * 注意它兜的是**渲染期**抛错，不兜事件回调与异步代码里的异常（那些走各自的 catch）。
 */
export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): { error: Error } {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // 组件栈太长，塞进 UI 会挤掉正文；这里落到控制台供排查
    console.error('[ErrorBoundary] 渲染抛错：', error, info.componentStack);
  }

  private retry = (): void => {
    this.setState({ error: null });
  };

  render(): ReactNode {
    const { error } = this.state;
    if (!error) return this.props.children;
    const chunk = isChunkLoadFailure(error);
    return (
      <div
        role="alert"
        style={{
          padding: '14px 16px',
          border: '1px solid var(--danger)',
          borderRadius: 'var(--r-md)',
          background: 'var(--danger-soft)',
          color: 'var(--danger-fg)',
        }}
      >
        <div style={{ fontSize: 13, fontWeight: 600 }}>
          {chunk ? '这一页的代码没取到，多半是控制台刚更新过' : '该模块加载失败，请重试'}
        </div>
        <div style={{ marginTop: 6, fontSize: 12, lineHeight: 1.6, opacity: 0.85 }}>
          {this.props.label ? `${this.props.label} · ` : ''}
          {truncate(error.message || String(error), 240)}
        </div>
        {chunk ? (
          <Button size="small" onClick={() => window.location.reload()} style={{ marginTop: 10 }}>
            刷新页面
          </Button>
        ) : (
          <Button size="small" onClick={this.retry} style={{ marginTop: 10 }}>
            重试
          </Button>
        )}
      </div>
    );
  }
}
