ARG PG_VERSION=v5.4.1
FROM pasarguard/panel:${PG_VERSION}

# Node REST client: force the ALPN http/1.1 context. The default context lets the
# Iran node negotiate h2, which stalled large /start bodies (panel → LockControl).
RUN f=/code/.venv/lib/python3.14/site-packages/PasarGuardNodeBridge/rest.py \
 && if grep -q 'ssl_context=self.ctx,' "$f"; then \
      sed -i 's/ssl_context=self.ctx,/ssl_context=self.http1_ctx,/' "$f"; \
    fi
