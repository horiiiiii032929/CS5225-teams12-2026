import { Link, Outlet } from '@tanstack/react-router';

export function AppLayout() {
  return (
    <>
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <Outlet />
    </>
  );
}
export function NotFoundPage() {
  return (
    <main id="main-content" className="status-shell">
      <h1>Page not found</h1>
      <Link to="/" search={{ review: 'create' }}>
        Return home
      </Link>
    </main>
  );
}
