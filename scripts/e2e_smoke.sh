#!/bin/bash
# Test e2e minimal : 1 seule source -> prompt court -> prefill rapide
set -e
API=http://localhost:8000

echo "=== /chat/start ==="
START=$(curl -s -X POST $API/chat/start -H 'Content-Type: application/json' \
  -d '{"question": "Quel modele Docling utilise-t-il pour les tableaux ?"}')
THREAD=$(echo "$START" | python3 -c "import sys,json; print(json.load(sys.stdin)['thread_id'])")
BEST=$(echo "$START" | python3 -c "
import sys, json
d = json.load(sys.stdin)
chunks = [c for g in d['groups'] for c in g['chunks']]
# le chunk le plus court parmi les 3 meilleurs : section reconstruite minimale
best = min(chunks[:3], key=lambda c: len(c['document']))
print(best['element_id'])
")
echo "thread=$THREAD best_id=$BEST"

echo "=== /chat/resume (1 source, streaming) ==="
START_TS=$(date +%s)
timeout 900 curl -s -N -X POST $API/chat/resume -H 'Content-Type: application/json' \
  -d "{\"thread_id\": \"$THREAD\", \"question\": \"q\", \"selected_element_ids\": [\"$BEST\"], \"stream\": true}" \
  > /tmp/sse_mini.txt || true
END_TS=$(date +%s)
echo "durée: $((END_TS - START_TS))s ; tokens: $(grep -c '\"token\"' /tmp/sse_mini.txt || true)"
grep '"done"' /tmp/sse_mini.txt | sed 's/^data: //' | python3 -c "
import sys, json
d = json.loads(sys.stdin.read())
print('--- ANSWER ---')
print(d['answer'][:500])
print('--- citations:', len(d['citations']), '| images:', len(d['images']), '| search_count:', d['search_count'])
for c in d['citations'][:4]:
    print(f\"  [{c['element_id']}] {c['filename']} p.{c['page_no']}\")
for i in d['images'][:4]:
    print(f\"  IMG {i['minio_url']}\")
" || echo "(pas d'événement done)"
