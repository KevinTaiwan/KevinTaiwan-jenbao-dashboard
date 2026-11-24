# Visitor API V4 (not deployed)
1. In Cloudflare Workers & Pages create a Worker, paste worker.mjs in its editor.
2. Create D1 database jenbao-visitors-v4. Run schema.sql in its console.
3. Bind D1 to the Worker with variable DB. Deploy and copy the actual Worker URL.
4. Check GET <worker URL>/visitors returns version v4, date, today, total. A zero is legitimate before first registration.
5. Only then change public/index.html CSP connect-src and visitor script to use the new URL. Browser creates a random UUID in localStorage, POSTs {"id":uuid} to /visitors and reads the returned counts. A GET refresh does not count; POST is idempotent on each date and lifetime. Test two distinct browsers on same Wi-Fi, refresh and next Taipei day.
No credentials belong in this public repo. Cloudflare origin checks are not authentication; public writes remain vulnerable to fabricated UUIDs. Add Cloudflare rate limiting/abuse protection as needed. No old CounterAPI counts are migrated because they are unverified. Worker code and database schema only; production Dashboard stays unchanged until deployment and validation.
