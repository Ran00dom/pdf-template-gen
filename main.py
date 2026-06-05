
import http.server as HttpServer
from http.server import BaseHTTPRequestHandler
import json
import sqlite3
from xhtml2pdf import pisa
import uuid
from io import BytesIO
import re

class ServerRequestHandler(BaseHTTPRequestHandler):
    def __init__(self, request, client_address, server):
        self.conn = sqlite3.connect('templates.db')
        cursor = self.conn.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS templates (id STRING PRIMARY KEY, name TEXT, content TEXT)")
        self.cursor = cursor
        super().__init__(request, client_address, server)

    def _send_json(self, data, status=200):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))

    def _send_response(self, data, content_type="text/html", status=200):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data))) 
        self.end_headers()

        if isinstance(data, str):
            self.wfile.write(data.encode('utf-8'))
        else:
            self.wfile.write(data)

    def do_GET(self):
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(UI.encode())
        
        elif self.path == "/templates":
            rows = self.cursor.execute("SELECT id, name FROM templates").fetchall()
            # print("Templates in DB:", rows) 
            self._send_json([{"id": r[0], "name": r[1]} for r in rows])
     
        elif self.path.startswith("/templates/"):
            tid = self.path.split("/")[-1]
            row = self.cursor.execute("SELECT id, name, content FROM templates WHERE id=?", (tid,)).fetchone()
            if row:
                self._send_json({"id": row[0], "name": row[1], "content": row[2]})
            else:
                self.send_error(404)

    def do_POST(self):
        content_length = int(self.headers['Content-Length'])
        body = json.loads(self.rfile.read(content_length))
        #print("Received POST data:", )

        clean_path = self.path.rstrip('/')
        if clean_path == "/templates":
            tid = str(uuid.uuid4())[:8] # создаем уникальный uuid
            self.cursor.execute("INSERT INTO templates VALUES (?, ?, ?)", (tid, body['name'], body['content']))
            self.conn.commit()
            self._send_json({"id": tid, "name": body['name']}, status=201)
            print("Template saved:", body['name'])

        elif self.path.startswith("/render/") or self.path.startswith("/preview/"):
            mode = "render" if "render" in self.path else "preview"
            tid = self.path.split("/")[-1]
            row = ''
            if tid == "new":
                row = body['html']
            else:
                row = self.cursor.execute("SELECT content FROM templates WHERE id=?", (tid,)).fetchone()
                if not row: return self.send_error(404)
                row = row[0]
            
            if not row: return self.send_error(404)
            
            
            if mode == "preview" and body['fields'] == {}:
                template_content = row
            else:
                pattern = r"\[%=\s*([a-zA-Z0-9_\-]+)\s*%\]"
                fields = body['fields']

                def replace_match(match):
                    key = match.group(1)  
                    return str(fields.get(key, match.group(0)))
                
                # Применяем регулярное выражение к строке шаблона
                template_content = re.sub(pattern, replace_match, row)
            # print(row)

            result = BytesIO()

            pisa_pdf = pisa.CreatePDF(
                BytesIO(template_content.encode('utf-8')), 
                dest=result,
                encoding='utf-8'
            )
            
            if pisa_pdf.err:
                return self.send_error(500, "PDF generation failed")
        
            self._send_response(result.getvalue(), content_type="application/pdf")

    def do_PUT(self):
        if self.path.startswith("/templates/"):
            tid = self.path.split("/")[-1]
            content_length = int(self.headers['Content-Length'])
            body = json.loads(self.rfile.read(content_length))
            self.cursor.execute("UPDATE templates SET name=?, content=? WHERE id=?", (body['name'], body['content'], tid))
            self.conn.commit()
            self._send_json({"status": "updated"})

    def do_DELETE(self):
        if self.path.startswith("/templates/"):
            tid = self.path.split("/")[-1]
            self.cursor.execute("DELETE FROM templates WHERE id=?", (tid,))
            self.conn.commit()
            self._send_json({})

UI = r"""
<!-- Include stylesheet -->

<link href="https://cdn.jsdelivr.net/npm/quill@2.0.3/dist/quill.snow.css" rel="stylesheet" />

<style>

    html, body {
        margin: 0;
        padding: 0;
        height: 100vh;
        width: 100vw;
        overflow: hidden;
    }

    #workspace {
        display: grid; 
        grid-template-columns: 1fr 1fr;
        height: 100vh;
        width: 100vw;
        overflow: hidden;
    }

    #menu {
       display: flex;
        gap: 10px;
        align-items: center;
    }

    .editor-wrapper {
        grid-column: 1;
        display: flex;
        flex-direction: column;
        height: 100vh;    
    }

    .ql-toolbar {
        flex-shrink: 0 !important;   
        border-top: none !important;
        border-left: none !important;
        border-right: none !important;
    }

    .ql-container {
        flex: 1 !important;          
        overflow-y: auto !important; 
        min-height: 0 !important;    
        border: none !important;
    }

    #preview-container {
        grid-column: 2;
        background-color: #525659; 
        display: flex;
        justify-content: center;
        align-items: center;
        padding: 15px;
        box-sizing: border-box;
        height: 100vh;  
        overflow: hidden;
    }

    .pdf-frame {
        width: 100%;
        height: 100%;
        border: none;
        background-color: #ffffff;
        box-shadow: 0 4px 12px rgba(0,0,0,0.3);
    }
</style>

<!-- Create the editor container -->
<div id="workspace">
  <div class="editor-wrapper">
    <div id="menu">
        <input id="template-name" placeholder="Template Name" style="margin: 10px; align-self: flex-end;"></input>
        <button id="save-btn" style="margin: 10px; align-self: flex-end;">Save Template</button>
        <button id="render-btn" style="margin: 10px; align-self: flex-end;">Render PDF</button>
        <select id="templates" name="templates" style="margin: 10px; align-self: flex-end; ">
        </select>
        <button id="delete-btn" style="margin: 10px; align-self: flex-end;">Delete Template</button>
    </div>
    <div id="editor">
      <h1>[%=game_date%] - test title</h1>
      <p><br></p>
      <p><br></p>
      <p><strong>Nom :</strong> [%=name%]</p>
      <p><strong>Tel :</strong> [%=phone%]</p>
      <p><strong>EMail :</strong> [%=email%]</p>
      <p>____________________________________________________</p>
      <p>[%=subtable%]</p>
    </div>
  </div>

  <div id="preview-container">
    <iframe id="pdf-viewer" class="pdf-frame"></iframe>
  </div>
</div>

<!-- Include the Quill library -->
<script src="https://cdn.jsdelivr.net/npm/quill@2.0.3/dist/quill.js"></script>

<!-- Initialize Quill editor -->
<script>

    // настройка инструментов редактора текста
    const fullToolbarOptions = [
        [{ 'header': [1, 2, 3, false] }, { 'font': [] }, { 'size': ['small', false, 'large', 'huge'] }],
        ['bold', 'italic', 'underline', 'strike'],        
        [{ 'color': [] }, { 'background': [] }],          
        [{ 'script': 'sub'}, { 'script': 'super' }],      
        [{ 'list': 'ordered'}, { 'list': 'bullet' }],
        [{ 'indent': '-1'}, { 'indent': '+1' }, { 'align': [] }],
        [{ 'direction': 'rtl' }], 
        ['link', 'image'],
        ['clean']                                         
        ];

    const quill = new Quill('#editor', {
        theme: 'snow',
        modules: {
            toolbar: fullToolbarOptions
        }
    });

    let currentBlobUrl = null; // ссылка на pdf файл
    let debounceTimer; 
    let isProgrammaticChange = false; // Флаг программного изменения текста
    let previousTemplateId = document.getElementById('templates').value; // предыдущий выбранный шаблон (требуется для сохранения, так как событие сохранение активируется когда пользователь уже выбрал другой шаблон)
    let save_render_data = {}; // сохранение данных подстановки для повторных запросов

//-------------------------------------------------
// Функция инициализации 
    function connect() {

        const start_editor = quill.root.innerHTML;
        
        // Превичное заполнение выпадающего списка шаблонов
        fetch('/templates')
            .then(response => 
            {
                console.log("HTTP Status of server response:", response.status);
                return response.json()
            })
            .then(templates => {
                const select = document.getElementById('templates');
                select.innerHTML = '<option value="new" selected>New Template</option>';
                if (templates && Array.isArray(templates)) {
                    templates.forEach(t => {
                        if (!t.id || !t.name) return; 

                        const option = document.createElement('option');
                        option.value = t.id; 
                        option.textContent = t.name;
                        select.appendChild(option);
                });
            } else {
                console.log("Template not exists or backend returned non-array:", templates);
            }
        })
        .catch(err => console.error("Error fetching template list:", err));


        document.getElementById('render-btn').addEventListener('click', function() {
            const htmlContent = quill.root.innerHTML;
            const regex = /\[%=\s*([a-zA-Z0-9_]+)\s*%\]/g; // регулярное выражение
            const parameters = new Set(); // Каждый ключь уникален
            let match;

            while ((match = regex.exec(htmlContent)) !== null) {
                parameters.add(match[1]); 
            }

            if (parameters.size === 0) {
                alert("Variables for filling not found. Rendering as is.");
                sendToRender(htmlContent);
                return;
            }

            let iframe = document.getElementById('render-iframe');

            if (!iframe) {
                iframe = document.createElement('iframe');
                iframe.id = 'render-iframe';
                // стили
                iframe.style.position = 'fixed';
                iframe.style.top = '10%';
                iframe.style.left = '25%';
                iframe.style.width = '50%';
                iframe.style.height = '70%';
                iframe.style.backgroundColor = '#fff';
                iframe.style.boxShadow = '0 4px 15px rgba(0,0,0,0.3)';
                iframe.style.border = '1px solid #ccc';
                iframe.style.zIndex = '9999';
                document.body.appendChild(iframe);
            }

            const iframeDoc = iframe.contentDocument || iframe.contentWindow.document;
            iframeDoc.open();

            // Пишем базовую разметку и стили формы внутрь фрейма
            iframeDoc.write(`
                <html>
                <head>
                    <style>
                        body { font-family: Arial, sans-serif; padding: 20px; color: #333; }
                        h3 { margin-top: 0; color: #0056b3; }
                        .form-group { margin-bottom: 15px; display: flex; flex-direction: column; }
                        label { font-weight: bold; margin-bottom: 5px; text-transform: capitalize; }
                        input { padding: 8px; border: 1px solid #ccc; border-radius: 4px; font-size: 14px; }
                        .actions { margin-top: 20px; display: flex; gap: 10px; }
                        button { padding: 10px 15px; border: none; border-radius: 4px; cursor: pointer; font-size: 14px; }
                        .btn-submit { background-color: #28a745; color: white; }
                        .btn-close { background-color: #dc3545; color: white; }
                    </style>
                </head>
                <body>
                    <h3>Fill in the details for the template</h3>
                    <form id="param-form">
                        <div id="fields-container"></div>
                        <div class="actions">
                            <button type="submit" class="btn-submit">Confirm and Render</button>
                            <button type="button" class="btn-close" id="close-iframe-btn">Cancel</button>
                        </div>
                    </form>
                </body>
                </html>
            `);

            iframeDoc.close();

            // Генерируем поля Label и Input внутри iframe для каждого параметра
            const fieldsContainer = iframeDoc.getElementById('fields-container');
            parameters.forEach(param => {
                const group = iframeDoc.createElement('div');
                group.className = 'form-group';

                const label = iframeDoc.createElement('label');
                label.textContent = param.replace('_', ' ') + ':';

                const input = iframeDoc.createElement('input');
                input.type = 'text';
                input.name = param; // Имя инпута соответствует переменной
                input.placeholder = `Input ${param}...`;
                if (save_render_data) {
                    input.value = save_render_data[param];
                }

                group.appendChild(label);
                group.appendChild(input);
                fieldsContainer.appendChild(group);
            });

            // Обработка кнопки отмены внутри iframe
            iframeDoc.getElementById('close-iframe-btn').addEventListener('click', function() {

                const formData = new FormData(this.closest('form'));
                const userValues = {};
                formData.forEach((value, key) => {
                    userValues[key] = value;
                });
                save_render_data = userValues; // Сохраняем введеные данные
                iframe.remove();
            });

            // Обработка отправки формы 
            iframeDoc.getElementById('param-form').addEventListener('submit', function(e) {
                e.preventDefault(); // Предотвращаем перезагрузку страницы

                // Собираем данные из инпутов в объект 
                const formData = new FormData(this);
                const userValues = {};
                formData.forEach((value, key) => {
                    userValues[key] = value;
                });
                save_render_data = userValues; // Сохраняем введеные данные
                console.log("Введенные пользователем данные:", userValues);

                // Делаем копию оригинального HTML из Quill
                let finalHtml = quill.root.innerHTML;

                // Удаляем iframe, так как данные успешно собраны
                iframe.remove();

                // Отправляем готовый HTML с данными на сервер для генерации PDF
                sendToRender(finalHtml, userValues);
            });
        });

        // Функция рендера
        function sendToRender(readyHtml, savedFields = {}) {
            console.log("HTML ready for PDF rendering:", readyHtml);
            
            fetch(`/render/${document.getElementById('templates').value}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ 
                    html: readyHtml,
                    fields: savedFields // Передаем сохраненные поля
                })
            })
            .then(response => {
                if (response.ok) return response.blob(); 
                return response.json();
            })
            .then(blobOrData => {
                // Логика отображения скачивания PDF
                const iframe = document.getElementById('pdf-viewer');
                if (iframe) {

                    if (currentBlobUrl) {
                        URL.revokeObjectURL(currentBlobUrl);
                    }
                    // Создаем свежий Blob-URL
                    currentBlobUrl = URL.createObjectURL(blobOrData);
                    
                    const link = document.createElement('a');
                    link.href = currentBlobUrl;
                    link.download = `document_${Date.now()}.pdf`; 
                    link.click();
                    link.remove()
                    // Присваиваем с флагом toolbar
                    iframe.src = currentBlobUrl + '#toolbar=1';

                }
                console.log("Render response received.");
            })
            .catch(err => console.error("Error rendering:", err));
        }

        // Сохранение текущего шаблона
        document.getElementById('save-btn').addEventListener('click', function() {
            const templateName = document.getElementById('template-name').value;
            fetch('/templates', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ name: templateName, content: quill.root.innerHTML })
            }).then(response => response.json())
            .then(data => {
                    selectTemplate(data.id)
                    addSelectedTemplate(data); // Обновляем селектор, добавляя новый шаблон
            });
        });

        // Удаление выбранного шаблона
        document.getElementById('delete-btn').addEventListener('click', function() {
            const pop_window = window.confirm("Are you sure you want to delete this template?");
            if (!pop_window) return;
            fetch(`/templates/${document.getElementById('templates').value}`, {
                method: 'DELETE'
            }).then(response => {
                if (response.ok) {
                    // Успешно удалено, обновляем селектор
                    const select = document.getElementById('templates');
                    const optionToRemove = select.querySelector(`option[value="${document.getElementById('templates').value}"]`);
                    if (optionToRemove) {
                        optionToRemove.remove();
                        select.value = "new"; // Сбрасываем на "New Template"
                        quill.root.innerHTML = start_editor; // Сбрасываем редактор
                    }
                } else {
                    console.error("Error deleting template:", response.status);
                }
            }).catch(err => console.error("Error deleting template:", err));
        });

        // Выбор другого шаблона
        document.getElementById('templates').addEventListener('change', function() {
            selectTemplate(this.value)
        });
  }

  connect();

// ---------------------=-----------------------------
    // обновление превью страницы
    function setPreview() {
        fetch(`/preview/${document.getElementById('templates').value}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                html: quill.root.innerHTML,
                fields: save_render_data
            })
        })
        .then(response => {
            if (response.ok) return response.blob(); // Если сервер возвращает PDF файл в виде байтов
            return response.json();
        })
        .then(blobOrData => {
            // Логика отображения PDF
            const iframe = document.getElementById('pdf-viewer');
            if (iframe) {
                if (currentBlobUrl) {
                    URL.revokeObjectURL(currentBlobUrl);
                }
                
                // Создаем свежий Blob-URL
                currentBlobUrl = URL.createObjectURL(blobOrData);
                
                // Присваиваем с флагом toolbar для вовыда понели управления pdf
                iframe.src = currentBlobUrl + '#toolbar=1';
            }
            console.log("Render response received.");
        })
        .catch(err => console.error("Error rendering:", err));
    }

    async function selectTemplate(targetValue) {

        // Пытаемся сохранить прошлый шаблон
        try {
            await updateSaveTemplate(); // ждем сохранения
            console.log("Current template saved before loading new one.");
        } catch (error) {
            console.error("Can't update template:", error);
            return; // Прерываем дальнейшее выполнение, чтобы не загружать новый шаблон
        }    
    
        previousTemplateId = targetValue; // заменяем индикатор предыдущего шаблона на выбранный 
        // востанавливаем редактор для выбранного шаблона через запрос
        if ("new" === targetValue) { // Если выбран новый шаблон то вводим стартовый заполнитель
            quill.root.innerHTML = start_editor;
        } else {
            console.log("Selected Template ID:", targetValue);
            fetch(`/templates/${targetValue}`)
                .then(response => response.json())
                .then(data => {
                    isProgrammaticChange = true;
                    quill.root.innerHTML = data.content;
                    setTimeout(() => {
                        isProgrammaticChange = false;
                        setPreview()
                    }, 50);
                });
        }
    }
    

    // Добавление нового шаблона в select
    function addSelectedTemplate(data) {
        const select = document.getElementById('templates');
        const option = document.createElement('option');
        option.value = data.id; // uuid
        option.textContent = data.name;
        select.appendChild(option);
        select.value = data.id; 
    }
    
    // Обновление сохраненных шаблонов
    function updateSaveTemplate() {

        const selectElement = document.getElementById("templates");
        const template = previousTemplateId;
        if (template && template !== "new") {
            
            const option = Array.from(selectElement.options).find(opt => opt.value === template);
            const templateName = option ? option.textContent : "Template";

            return fetch(`/templates/${template}`, { // возвращаем результат асинхронного вызова для последовательного вызова при сохранении
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ 
                    name: templateName,
                    content: quill.root.innerHTML 
                })
            })
            .then((response) => {
                console.log("HTTP status preview:", response.status);
                return response.json();
            })
            .then((data) => {
                console.log("Data preview:", data);
                return data;
            });
        }

        return Promise.resolve(); // возвращаем индикатор завершения потока
    }

    // Первичный запуск 
    setTimeout(() => {
        updateSaveTemplate();
        setPreview();
    }, 200);
  
    // Сохранение шаблона и отрисовка pdf после ввода новых данных в шаблон
    quill.on('text-change', function() {
        if (isProgrammaticChange) return;

        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(function() {
            updateSaveTemplate();
            setPreview();
        }, 1000);
    });
</script>
"""

if __name__ == "__main__":
    server = HttpServer.HTTPServer(('localhost', 8000), ServerRequestHandler)
    class_handler = server.RequestHandlerClass;

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Server stopped.")


