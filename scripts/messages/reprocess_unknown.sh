#!/bin/bash
# Скрипт для переобработки диалогов с "unknown" участниками

ACCOUNT="${1:-ychukaev}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DB_PATH="$SCRIPT_DIR/../accounts/$ACCOUNT/messages.sqlite"

echo "🔍 Ищем диалоги с 'unknown' участниками..."
echo "📂 БД: $DB_PATH"

# Получаем список диалогов с unknown
DIALOGS=$(sqlite3 "$DB_PATH" "
SELECT DISTINCT dialog_id 
FROM dialog_contexts 
WHERE context_text LIKE '%unknown%'
   OR json_extract(context_json, '\$.participants') LIKE '%unknown%'
" 2>/dev/null)

COUNT=$(echo "$DIALOGS" | grep -c . )
echo "📊 Найдено диалогов: $COUNT"

if [ "$COUNT" -eq 0 ]; then
    echo "✅ Нет диалогов с unknown"
    exit 0
fi

echo "🗑️  Удаляем старые контексты и batch_requests..."

for dialog_id in $DIALOGS; do
    if [ -n "$dialog_id" ]; then
        # Удаляем контексты
        sqlite3 "$DB_PATH" "DELETE FROM dialog_contexts WHERE dialog_id = '$dialog_id'"
        
        # Удаляем batch_requests для этого диалога
        sqlite3 "$DB_PATH" "DELETE FROM batch_requests WHERE custom_id LIKE 'dlg:$dialog_id:%'"
        
        echo "  ✓ Очищен диалог $dialog_id"
    fi
done

echo ""
echo "✅ Готово! Теперь запустите:"
echo "   cd $SCRIPT_DIR"
echo "   python process_all.py --account $ACCOUNT --use-batch --max-dialogs $COUNT"
