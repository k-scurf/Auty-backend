# Database structure

Auty splits persistence into three stores under `data/` (gitignored).

## `face_db.pkl`

Python pickle dict:

```text
{
  "Alice": [ embedding_vector, ... ],
  "Bob": [ ... ],
}
```

- Each value is a list of L2-normalized ArcFace embeddings (numpy arrays).
- Matching uses **best cosine score** across all samples per person.
- Capped by `max_embeddings_per_person` in settings.

Managed by `database.FaceDatabase` (`FaceDatabase` class).

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
