import { createFileRoute } from '@tanstack/react-router';
import { HomePage } from '../pages/HomePage';
import { previews, type Preview } from '@/features/wireframes/model';

export const Route = createFileRoute('/')({
  validateSearch: (search: Record<string, unknown>): { review: Preview } => ({
    review: previews.includes(search.review as Preview)
      ? (search.review as Preview)
      : 'create',
  }),
  component: HomePage,
});
