import type { NextConfig } from 'next';
const config: NextConfig = {
  output: 'standalone',
  async rewrites() {
    return [{ source: '/v1/:path*', destination: `${process.env.BACKEND_URL || 'http://127.0.0.1:8000'}/v1/:path*` }];
  },
};
export default config;
