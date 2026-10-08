import { createFileRoute } from '@tanstack/react-router';
import { ServiceStatusPage } from '../pages/ServiceStatusPage';

export const Route = createFileRoute('/status')({
  component: ServiceStatusPage,
});
