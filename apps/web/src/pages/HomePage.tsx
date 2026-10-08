import { Link } from '@tanstack/react-router';

export function HomePage() {
  return (
    <section className="panel">
      <p className="eyebrow">Development workspace</p>
      <h1>Ready to build FlatSplit.</h1>
      <p>
        React, TanStack Router and TanStack Query are connected. The optional
        Python service and AWS infrastructure have their own workspace folders.
      </p>
      <Link className="button" to="/status">
        Check the API connection
      </Link>
    </section>
  );
}
