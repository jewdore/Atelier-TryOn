const backend = process.env.API_INTERNAL_URL || 'http://127.0.0.1:8000';
export default {
  output: 'standalone',
  experimental: { cpus: 2, proxyTimeout: 240000 },
  async rewrites() {
    return [
      { source: '/api/:path*', destination: `${backend}/api/:path*` },
      { source: '/garments/:path*', destination: `${backend}/garments/:path*` },
    ];
  },
};
