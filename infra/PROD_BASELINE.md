# Samvaad prod baseline (Phase 0 freeze)
Date (UTC): 2026-09-16
Git HEAD: 696dfa7 Update README documentation

## Chroma chunk counts (embeddings table per chroma.sqlite3)
25e0d279-e5d2-4fbf-ab82-71b363d8d909: 38
3ce706c5-1fd5-4f43-9b02-14dd40c32313: 86
59cd412e-b479-40e5-b07c-5e68e7cc1b74: 25
6115a6c2-f52f-4885-8b4c-073d2c09878e: 173
739b5a29-7c50-4a48-98fd-793a80cee979: 38
770ce124-1ee2-4d06-8840-fa7a705748f0: 173
8495af34-aa50-40d2-a30c-004e825551ca: 25
8ef0c105-6025-4042-8c8d-bf2b1481b370: 86
8f82d715-1689-468b-8ba5-fad7b2b3d419: 25
c093897d-3299-42e7-ad76-c288e4fc8f88: 173
c7a5b930-75f7-4532-8884-5fb0d861e6e9: 38
convs/05909e35-b30a-478a-8df4-22ab642eef88: 87
convs/77f89ec0-d88b-4129-9c75-d8bfb76c5ade: 87
convs/8afbfd0f-959d-4006-b786-ae06dc2be559: 87
convs/8d099f48-b21c-41f0-a496-de07af0f60e3: 87
convs/99f69ecf-a62e-4667-84c6-1862a8e31cfb: 87
org_6b17118a-cf93-407e-9aa7-8a9c615e2291: 728
user_92c53b6e-4d70-4ec1-8be2-ee7b45d74f0b: 728
TOTAL chunks: 2771
Disk: backend/chroma_db_api = 160M

## Notes
- Parity gate for Phase 2 PGVector migration: PG total must equal 2771 and per-conv counts must match.
- Dev compose unchanged; prod override is docker-compose.prod.yml.
