# Release flow

```
dev  ──PR──►  main (staging)  ──PR──►  prod
```

- **dev**: active development branch; merges to `main` via pull request
- **main**: staging environment; merges to `prod` via pull request after validation
- **prod**: production branch; deployed to AWS EC2 and served via the Cloudflare Worker proxy at [skinet.pkliuiev.workers.dev](https://skinet.pkliuiev.workers.dev)

## Production routing

Nginx listens on port 80 and routes:
- `/api/*` → Node.js backend (port 5000)
- everything else → React frontend (port 3000)

To start production services manually:

```bash
docker compose -f docker-compose.yml up --build -d
```
