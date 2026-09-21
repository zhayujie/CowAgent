import json
from pathlib import Path
from unittest.mock import patch


def test_knowledge_action_handler_delegates_to_dispatch(tmp_path):
    from channel.web.api.knowledge import KnowledgeActionHandler

    request = {"action": "create_category", "payload": {"path": "research"}}
    dispatched = {"action": "create_category", "code": 200, "message": "success",
                  "payload": {"path": "research", "created": True}}

    with patch("channel.web.api.knowledge._require_auth"), \
         patch("channel.web.api.knowledge.web.header"), \
         patch("channel.web.api.knowledge.web.data", return_value=json.dumps(request).encode()), \
         patch("channel.web.api.knowledge._get_workspace_root", return_value=str(tmp_path)), \
         patch("agent.knowledge.service.KnowledgeService.dispatch", return_value=dispatched) as dispatch:
        response = json.loads(KnowledgeActionHandler().POST())

    dispatch.assert_called_once_with("create_category", {"path": "research"})
    assert response["status"] == "success"
    assert response["payload"]["created"] is True


def test_knowledge_action_handler_reindexes_behind_the_response(tmp_path):
    """The reindex may wait on an embedding call or on the Agent holding the
    index. The console's save must not."""
    from channel.web.api.knowledge import KnowledgeActionHandler

    request = {"action": "update_document", "payload": {"path": "a.md", "content": "x"}}
    seen = {}

    def dispatch(self, action, payload):
        seen["background"] = self.reindex_in_background
        return {"action": action, "code": 200, "message": "success", "payload": {}}

    with patch("channel.web.api.knowledge._require_auth"), \
         patch("channel.web.api.knowledge.web.header"), \
         patch("channel.web.api.knowledge.web.data", return_value=json.dumps(request).encode()), \
         patch("channel.web.api.knowledge._get_workspace_root", return_value=str(tmp_path)), \
         patch("agent.knowledge.service.KnowledgeService.dispatch", dispatch):
        KnowledgeActionHandler().POST()

    assert seen["background"] is True


def test_knowledge_action_handler_preserves_dispatch_error(tmp_path):
    from channel.web.api.knowledge import KnowledgeActionHandler

    dispatched = {"action": "delete_documents", "code": 403,
                  "message": "protected knowledge file: index.md", "payload": None}
    request = {"action": "delete_documents", "payload": {"paths": ["index.md"]}}

    with patch("channel.web.api.knowledge._require_auth"), \
         patch("channel.web.api.knowledge.web.header"), \
         patch("channel.web.api.knowledge.web.data", return_value=json.dumps(request).encode()), \
         patch("channel.web.api.knowledge._get_workspace_root", return_value=str(tmp_path)), \
         patch("agent.knowledge.service.KnowledgeService.dispatch", return_value=dispatched):
        response = json.loads(KnowledgeActionHandler().POST())

    assert response["status"] == "error"
    assert response["code"] == 403
    assert response["message"] == "protected knowledge file: index.md"


def test_knowledge_frontend_management_contract():
    root = Path(__file__).parents[1]
    # The page is assembled from templates/, so assert against what is served.
    from channel.web.core import template
    html = template.render("chat.html")
    from conftest import console_js
    js = console_js()

    assert 'id="knowledge-dialog-overlay"' in html
    assert 'id="knowledge-dialog-textarea"' in html
    assert 'id="knowledge-document-form"' in html
    assert 'id="knowledge-document-path-preview"' in html
    assert "function openKnowledgeDialog(" in js
    assert "function _knowledgeCategoryPaths(" in js
    assert "dispatchKnowledgeAction('create_category'" in js
    assert "dispatchKnowledgeAction('create_document'" in js
    assert "dispatchKnowledgeAction('rename_category'" in js
    assert "dispatchKnowledgeAction('delete_category'" in js
    assert "dispatchKnowledgeAction('delete_documents'" in js
    assert "dispatchKnowledgeAction('move_documents'" in js
    assert 'id="knowledge-import-input"' in html
    assert "function createKnowledgeDocument(" in js
    assert "function openKnowledgeDocumentEditor(" in js
    assert "documentPathPreview.textContent = options.category" in js
    assert "options.type === 'document'" in js
    assert "input.classList.toggle('hidden', options.type === 'select' || options.type === 'textarea' || options.type === 'document')" in js
    assert "function selectKnowledgeImportFiles(" in js
    assert "function importKnowledgeDocuments(" in js
    assert "function validateKnowledgeImportFiles(" in js
    assert "KNOWLEDGE_IMPORT_MAX_FILE_SIZE" in js
    assert "fetch(_kbUrl('/api/knowledge/import')" in js
    assert "initKnowledgeImportDropZone()" in js

    knowledge_section = js[js.index("// Knowledge View"):js.index("function _hasFilterMatch")]
    assert "prompt(" not in knowledge_section
    assert "alert(" not in knowledge_section
    assert "if (path === 'index.md' || path === 'log.md') return '';" in knowledge_section


def test_knowledge_document_editor_contract():
    from channel.web.core import template
    html = template.render("chat.html")
    from conftest import console_js
    js = console_js()

    assert 'id="knowledge-btn-edit"' in html
    assert 'id="knowledge-btn-save"' in html
    assert 'id="knowledge-btn-cancel"' in html
    # The page's three editors share doc-editor.js, which therefore has to keep
    # loading before the views that build one at top level.
    assert html.index("/assets/js/doc-editor.js") < html.index("/assets/js/views/knowledge.js")
    assert "const knowledgeEditor = createDocEditor(" in js
    assert "action: 'update_document'" in js
    assert "expected_mtime: expectedMtime" in js
    assert "data.payload?.conflict ? 'conflict' : data.code" in js
    # Every way out of an open text area asks before dropping what is in it.
    assert "memoryEditor.guard(next) && skillEditor.guard(next) && knowledgeEditor.guard(next)" in js
    for leaving in ("openKnowledgeFile(path, title)", "switchKnowledgeTab(tab)",
                    "selectKnowledgeAgent(agentId)", "knowledgeMobileBack"):
        assert f"knowledgeEditor.guard(() => {leaving})" in js or \
               f"knowledgeEditor.guard({leaving})" in js


class UploadedFile:
    def __init__(self, filename, content):
        self.filename = filename
        self.value = content


def test_knowledge_import_handler_delegates_to_dispatch(tmp_path):
    from channel.web.api.knowledge import KnowledgeImportHandler

    dispatched = {"action": "import_documents", "code": 200, "message": "success",
                  "payload": {"imported": 2, "skipped": 0, "failed": 0}}
    params = {
        "target_category": "notes",
        "conflict_strategy": "rename",
        "files": [UploadedFile("a.md", b"# A"), UploadedFile("b.txt", b"B")],
    }

    with patch("channel.web.api.knowledge._require_auth"), \
         patch("channel.web.api.knowledge.web.header"), \
         patch("channel.web.api.knowledge._raw_web_input", return_value=params), \
         patch("channel.web.api.knowledge._get_workspace_root", return_value=str(tmp_path)), \
         patch("agent.knowledge.service.KnowledgeService.dispatch", return_value=dispatched) as dispatch:
        response = json.loads(KnowledgeImportHandler().POST())

    dispatch.assert_called_once()
    action, payload = dispatch.call_args.args
    assert action == "import_documents"
    assert payload["target_category"] == "notes"
    assert payload["conflict_strategy"] == "rename"
    assert [f["filename"] for f in payload["files"]] == ["a.md", "b.txt"]
    assert response["status"] == "success"
    assert response["payload"]["imported"] == 2


def test_knowledge_import_handler_rejects_large_content_length(tmp_path):
    from channel.web.api.knowledge import KnowledgeImportHandler
    from agent.knowledge.service import KnowledgeService
    assert KnowledgeService.MAX_IMPORT_TOTAL_SIZE == 200 * 1024 * 1024

    with patch("channel.web.api.knowledge._require_auth"), \
         patch("channel.web.api.knowledge.web.header"), \
         patch("channel.web.api.knowledge.web.ctx") as ctx:
        ctx.env = {"CONTENT_LENGTH": str(KnowledgeService.MAX_IMPORT_TOTAL_SIZE + 1)}
        response = json.loads(KnowledgeImportHandler().POST())

    assert response["status"] == "error"
    assert response["code"] == 413
    assert response["message"] == "import batch too large"
