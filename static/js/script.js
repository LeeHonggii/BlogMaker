let notebookData = null;
let streamContent = '';   // 스트리밍 컨텐츠 누적
const selectedCells = new Set();
const processButton = document.getElementById('processButton');
const copyButton = document.getElementById('copyButton');
const blogResult = document.getElementById('blogResult');

// Marked 설정 (코드 하이라이트 포함)
marked.setOptions({
    highlight: function(code, lang) {
        const language = hljs.getLanguage(lang) ? lang : 'plaintext';
        return hljs.highlight(code, { language }).value;
    },
    langPrefix: 'hljs language-',
});

// 상태별 메시지 정의
const STATUS_MESSAGES = {
   'start': '🚀 분석을 시작합니다...',
   'grouping': '🔄 분석 중입니다...',
   'analyzing': '🔄 분석 중입니다...',
   'generating': '✍️ 블로그를 작성중입니다...',
   'complete': '✅ 블로그 작성이 완료되었습니다!'
};

document.getElementById('fileInput').addEventListener('change', async (event) => {
   const file = event.target.files[0];
   if (!file) return;

   const reader = new FileReader();
   reader.onload = async (e) => {
       try {
           const content = JSON.parse(e.target.result);
           notebookData = content;
           displayNotebookContent(content);
           processButton.style.display = 'block';
       } catch (error) {
           console.error('Error parsing notebook:', error);
           alert('노트북 파일을 읽는 중 오류가 발생했습니다.');
       }
   };
   reader.readAsText(file);
});

function displayNotebookContent(notebook) {
   const contentDiv = document.getElementById('uploadedContent');
   contentDiv.innerHTML = '';

   notebook.cells.forEach((cell, index) => {
       const cellDiv = document.createElement('div');
       cellDiv.className = `cell-container ${cell.cell_type}-cell`;

       const cellHeader = document.createElement('div');
       cellHeader.className = 'cell-header';
       
       const cellTitle = document.createElement('span');
       cellTitle.className = 'cell-type-badge';
       cellTitle.textContent = `${cell.cell_type === 'code' ? '코드' : '마크다운'} 셀 ${index + 1}`;
       
       const checkbox = document.createElement('input');
       checkbox.type = 'checkbox';
       checkbox.title = '이 셀 제외하기';
       checkbox.onclick = () => toggleCellSelection(index);

       cellHeader.appendChild(cellTitle);
       cellHeader.appendChild(checkbox);
       cellDiv.appendChild(cellHeader);

       const contentPre = document.createElement('pre');
       contentPre.className = 'cell-content';
       contentPre.textContent = Array.isArray(cell.source) 
           ? cell.source.join('') 
           : cell.source;
       cellDiv.appendChild(contentPre);

       if (cell.outputs && cell.outputs.length > 0) {
           const outputsDiv = document.createElement('div');
           outputsDiv.className = 'output';
           cell.outputs.forEach(output => {
               if (output.text) {
                   const outputPre = document.createElement('pre');
                   outputPre.textContent = Array.isArray(output.text) 
                       ? output.text.join('') 
                       : output.text;
                   outputsDiv.appendChild(outputPre);
               }
           });
           cellDiv.appendChild(outputsDiv);
       }

       contentDiv.appendChild(cellDiv);
   });
}

function toggleCellSelection(index) {
   if (selectedCells.has(index)) {
       selectedCells.delete(index);
   } else {
       selectedCells.add(index);
   }
}

processButton.addEventListener('click', async () => {
    if (!notebookData) {
        alert('노트북 파일을 먼저 업로드해주세요.');
        return;
    }

    try {
        processButton.disabled = true;
        processButton.textContent = '처리 중...';
        streamContent = '';
        blogResult.innerHTML = `<p class="progress-message">🔄 분석 중입니다...</p>`;

        const processResponse = await fetch('/process-notebook/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                cells: notebookData.cells,
                excludedIndices: Array.from(selectedCells)
            })
        });

        if (!processResponse.ok) {
            throw new Error('노트북 처리 중 오류가 발생했습니다.');
        }

        const blogResponse = await fetch('/generate-blog');
        if (!blogResponse.ok) {
            throw new Error('블로그 생성 중 오류가 발생했습니다.');
        }

        const reader = blogResponse.body.getReader();
        const decoder = new TextDecoder();
        
        let isComplete = false;
        
        while (!isComplete) {
            const { value, done } = await reader.read();
            if (done) break;

            const chunk = decoder.decode(value);
            for (const line of chunk.split('\n')) {
                if (line.trim() && line.startsWith('data: ')) {
                    try {
                        const data = JSON.parse(line.slice(6));

                        if (data.type === 'status') {
                            const message = STATUS_MESSAGES[data.step];
                            if (message) {
                                const existingContent = blogResult.querySelector('.blog-content');
                                blogResult.innerHTML = `
                                    <p class="progress-message">${message}</p>
                                    ${existingContent ? existingContent.outerHTML : ''}
                                `;
                                
                                // complete 상태 확인
                                if (data.step === 'complete') {
                                    isComplete = true;
                                    break;
                                }
                            }
                        } 
                        else if (data.type === 'content') {
                            streamContent = data.data.content;
                            blogResult.innerHTML = `
                                <p class="progress-message">✍️ 블로그를 작성중입니다...</p>
                                <div class="blog-content">${marked.parse(streamContent)}</div>
                            `;
                        }
                        
                        blogResult.scrollTop = blogResult.scrollHeight;
                    } catch (parseError) {
                        console.error('JSON parse error:', parseError);
                    }
                }
            }
            
            // complete 상태면 루프 종료
            if (isComplete) break;
        }

        // 최종 완료 상태 처리
        blogResult.innerHTML = `
            <p class="progress-message">${STATUS_MESSAGES['complete']}</p>
            <div class="blog-content">${marked.parse(streamContent)}</div>
        `;
        processButton.textContent = '선택 완료';
        copyButton.style.display = 'block';
        processButton.disabled = false;
        
        // 코드 하이라이트 적용
        document.querySelectorAll('pre code').forEach((block) => {
            hljs.highlightBlock(block);
        });

    } catch (error) {
        console.error('Error:', error);
        blogResult.innerHTML = `<p class="error">❌ 오류 발생: ${error.message}</p>`;
        processButton.textContent = '선택 완료';
        processButton.disabled = false;
    }
});

copyButton.addEventListener('click', () => {
   navigator.clipboard.writeText(streamContent)
       .then(() => {
           const originalText = copyButton.textContent;
           copyButton.textContent = '복사 완료!';
           setTimeout(() => {
               copyButton.textContent = originalText;
           }, 2000);
       })
       .catch(err => {
           console.error('복사 실패:', err);
           alert('콘텐츠 복사 중 오류가 발생했습니다.');
       });
});