import { useSearch } from '@tanstack/react-router';
import { WireframeApp } from '@/features/wireframes/WireframeApp';

export function HomePage() {
  const { review } = useSearch({ from: '/' });
  return <WireframeApp key={review} initialPreview={review} />;
}
