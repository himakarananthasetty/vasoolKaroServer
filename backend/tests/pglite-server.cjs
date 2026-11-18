// Disposable test database: runs a real (WASM) Postgres over the Postgres wire
// protocol via @electric-sql/pglite-socket. No system Postgres needed.
// Setup: cd tests && npm i
// Run:   node tests/pglite-server.cjs   → postgresql://postgres:postgres@127.0.0.1:54329/postgres
const { PGLiteSocketServer } = require('@electric-sql/pglite-socket');
const { PGlite } = require('@electric-sql/pglite');

const port = parseInt(process.env.PGLITE_PORT || '54329', 10);
const dataDir = process.env.PGLITE_DATA || '/tmp/pglite-data';

async function main() {
  const db = new PGlite(dataDir);
  const server = new PGLiteSocketServer({ db, port, host: '127.0.0.1', maxConnections: 10 });
  await server.start();
  console.log(`pglite test postgres listening on 127.0.0.1:${port}`);
}

main().catch((err) => {
  console.error('failed to start:', err);
  process.exit(1);
});
