import { Component, type ReactNode } from "react";

export class ErrorBoundary extends Component<
  { children: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    if (this.state.failed)
      return (
        <main className="empty" style={{ margin: "12vh auto", maxWidth: 560 }}>
          <h1>Let’s reopen the workspace.</h1>
          <p>
            The client encountered an unexpected problem. Reload to start a
            fresh session; you’ll need to reconnect your credential.
          </p>
          <button className="button primary" onClick={() => location.reload()}>
            Reload workspace
          </button>
        </main>
      );
    return this.props.children;
  }
}
