import { Link, Outlet } from '@tanstack/react-router';

export function AppLayout() {
  return (
    <div className="shell">
      <header>
        <Link className="brand" to="/">
          FlatSplit
        </Link>
        <nav aria-label="Main navigation">
          <Link
            to="/"
            activeOptions={{ exact: true }}
            activeProps={{ 'aria-current': 'page' }}
          >
            Home
          </Link>
          <Link to="/status" activeProps={{ 'aria-current': 'page' }}>
            Service status
          </Link>
        </nav>
      </header>
      <main>
        <Outlet />
      </main>
      <footer>Repository scaffold · CS5224</footer>
    </div>
  );
}

export function NotFoundPage() {
  return (
    <section className="panel">
      <h1>Page not found</h1>
      <Link to="/">Return home</Link>
    </section>
  );
}
