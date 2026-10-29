import base from '../../apps/web/vite.config.ts';
export default {
  ...base,
  root: new URL('../../apps/web', import.meta.url).pathname,
  server: {
    ...base.server,
    port: 5180,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8010',
        rewrite: (path: string) => path.replace(/^\/api/, ''),
      },
    },
  },
};
