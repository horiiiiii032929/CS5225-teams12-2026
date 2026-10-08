import { createRootRouteWithContext } from '@tanstack/react-router';
import { AppLayout, NotFoundPage } from '../components/AppLayout';
import type { RouterContext } from '../router-context';

export const Route = createRootRouteWithContext<RouterContext>()({
  component: AppLayout,
  notFoundComponent: NotFoundPage,
});
