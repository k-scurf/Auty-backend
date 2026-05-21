# Database structure

Auty splits persistence into three stores under `data/` (gitignored).

## Identity v2 (`data/identities/`)

Each person has a UUID folder:

```text
data/identities/{uuid}/
  meta.json          # name, enrolled_at, poses, profile metadata
  embeddings.npy     # all sample embeddings
  images/*.jpg       # enrollment crops
```

- **Master embedding** — mean of samples, L2-normalized, used for fast matching.
- Legacy `face_db.pkl` is migrated on first load via `scripts/migrate_identity_v2.py`.
- A pickle mirror of name → embeddings is still written for compatibility.

Managed by `vision.identity_store.IdentityStore` (facade: `database.FaceDatabase`).

## `profiles.json`

JSON object keyed by canonical identity name:

```json
{
  "Alice": {
    "name": "Alice Smith",
    "age": "28",
    "status": "FRIEND",
    "image": "captures/Alice.jpg"
  }
}
```

Used for HUD display and relationship tier (OWNER / FRIEND / UNKNOWN).

## `memory.json`

Social layer via `memory_manager.py`:

- `visit_count`, `last_seen`, `relationship_score`
- Event history: `greeting`, `seen`, `enrolled`, etc.

Accessed through `memory.Memory` facade for the response engine.

## Captures

`data/captures/*.jpg` — enrollment snapshots and optional unknown snapshots from HUD.

## Reset

`reset_db_each_run: true` in settings clears embeddings and profiles on each launch (dev only). Default in example config is `false`.

## Backup

Copy the entire `data/` folder to backup identities. Never commit it to a public repository.
