"use strict";

const el = id => document.getElementById(id);
const maxChars = 60000;
const initialSummary = el("summary").textContent;
const initialChatHelp = el("chatHelp").textContent;
let version = 0;
let originalFile = null;
let reviewed = null;
let proposal = null;
let approved = null;
let history = [];

function status(message, error = false) {
  el("status").textContent = message;
  el("status").classList.toggle("error", error);
}

function node(tag, text, className) {
  const element = document.createElement(tag);
  element.textContent = text;
  if (className) element.className = className;
  return element;
}

function resetReview() {
  version++;
  reviewed = proposal = approved = null;
  history = [];
  el("review").disabled = false;
  el("preview").disabled = false;
  el("preview").hidden = el("diffBox").hidden = el("download").hidden = true;
  el("question").disabled = el("send").disabled = true;
  el("question").value = "";
  el("chatStatus").textContent = el("count").textContent = "";
  el("summary").textContent = initialSummary;
  el("findings").replaceChildren();
  el("diff").replaceChildren();
  el("messages").replaceChildren(node("p", initialChatHelp));
  return version;
}

function source() {
  return {
    code: originalFile?.text ?? el("code").value,
    filename: el("name").value.trim() || "pasted_code"
  };
}

async function post(path, data) {
  const response = await fetch(path, {
    method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(data)
  });
  const body = await response.json();
  if (!response.ok) {
    const detail = Array.isArray(body.detail) ? body.detail.map(e => e.msg).join(". ") : body.detail;
    throw new Error(detail || "The request failed. Please try again.");
  }
  return body;
}

el("code").oninput = () => {
  // Textareas normalize line endings. Retain an uploaded file's originals until the first edit.
  originalFile = null;
  el("example").hidden = !!el("code").value;
  resetReview();
  status("Review this version to see findings.");
};
el("name").oninput = () => { resetReview(); status("Review this file to see findings."); };
fetch("/health").then(response => response.ok ? response.json() : null).then(health => {
  if (!health?.provider) return;
  el("provider").textContent = health.provider === "mock" ? "Offline demo" : "Provider · " + health.provider;
  el("provider").hidden = false;
}).catch(() => {});

el("example").onclick = () => {
  if (el("code").value) return;
  resetReview();
  originalFile = null;
  el("code").value = 'public class Role {\n    public boolean isAdmin(String role) {\n        return role == "admin";\n    }\n}\n';
  el("name").value = "Role.java";
  el("example").hidden = true;
  status("Example loaded. Select Review code to check the comparison.");
};
el("openFile").onclick = () => el("file").click();
el("file").onchange = async () => {
  const file = el("file").files[0];
  el("file").value = "";
  if (!file) return;
  const current = resetReview();
  try {
    if (file.size > maxChars * 4 + 3) throw new Error("Choose a text file with up to 60,000 characters.");
    const bytes = new Uint8Array(await file.arrayBuffer());
    if (current !== version) return;
    const text = new TextDecoder("utf-8", {fatal:true}).decode(bytes);
    if (text.includes("\0") || !text.trim()) throw new Error("Choose a nonempty UTF-8 text file.");
    if (Array.from(text).length > maxChars) throw new Error("Choose a text file with up to 60,000 characters.");
    originalFile = {text, bom: bytes[0] === 0xef && bytes[1] === 0xbb && bytes[2] === 0xbf};
    el("code").value = text;
    el("example").hidden = true;
    el("name").value = file.name;
    status("File opened. Select Review code to send it for review.");
  } catch (err) {
    if (current === version) status(err instanceof TypeError ? "Choose a UTF-8 text file." : err.message, true);
  }
};

el("review").onclick = async () => {
  const current = resetReview();
  const input = source();
  if (!input.code.trim() || Array.from(input.code).length > maxChars) {
    status("Enter 1 to 60,000 characters of source code.", true);
    return;
  }
  el("review").disabled = true;
  status("Reviewing the source…");
  try {
    const {review} = await post("/check", input);
    if (version !== current) return;
    reviewed = Object.freeze({...input, review, bom: originalFile?.bom ?? false});
    el("summary").textContent = review.summary;
    el("count").textContent = review.comments.length + (review.comments.length === 1 ? " finding" : " findings");
    for (const finding of review.comments) {
      const row = node("article", "", "finding");
      row.append(node("small", finding.severity.toUpperCase() + " · " + finding.category + " · line " + finding.line));
      row.append(node("p", finding.body));
      if (finding.suggestion) row.append(node("p", finding.suggestion, "suggestion"));
      el("findings").append(row);
    }
    el("preview").hidden = !review.comments.length;
    el("send").disabled = el("question").disabled = false;
    el("messages").replaceChildren(node("p", "What would you like to know about this review?"));
    status("Review complete. Your source is unchanged.");
  } catch (err) { if (version === current) status(err.message, true); }
  finally { if (version === current) el("review").disabled = false; }
};

el("preview").onclick = async () => {
  if (!reviewed) return;
  const current = version;
  el("preview").disabled = true;
  status("Preparing the proposed changes…");
  try {
    const result = await post("/preview", reviewed);
    if (current !== version) return;
    if (!result.diff || result.fixed_code === reviewed.code) {
      status(result.fix_notes || "The provider returned no changes.");
      return;
    }
    proposal = Object.freeze({...reviewed, fixed: result.fixed_code});
    el("diff").replaceChildren();
    for (const line of result.diff.split("\n")) {
      const kind = line.startsWith("+") && !line.startsWith("+++") ? "add" :
        line.startsWith("-") && !line.startsWith("---") ? "remove" : "";
      el("diff").append(node("span", line, kind));
    }
    el("notes").textContent = result.fix_notes;
    el("diffBox").hidden = false;
    el("preview").hidden = true;
    status("Review the diff. Apply these changes to the editor?");
    el("approve").focus();
  } catch (err) { if (current === version) status(err.message, true); }
  finally { if (current === version) el("preview").disabled = false; }
};

el("decline").onclick = () => {
  proposal = null;
  el("diffBox").hidden = true;
  el("preview").hidden = false;
  status("Changes declined. Your source is unchanged.");
};
el("approve").onclick = () => {
  const input = source();
  if (!proposal || input.code !== proposal.code || input.filename !== proposal.filename) {
    resetReview();
    status("The source changed. Review the current version before applying a fix.", true);
    return;
  }
  approved = proposal;
  version++;
  proposal = reviewed = null;
  el("question").disabled = el("send").disabled = true;
  originalFile = {text: approved.fixed, bom: approved.bom};
  el("code").value = approved.fixed;
  el("diffBox").hidden = true;
  el("download").hidden = false;
  el("chatStatus").textContent = "Review the fixed file to start a new discussion.";
  status("Changes applied to the editor. Download the fixed file or review it again.");
};
el("download").onclick = () => {
  if (!approved) return;
  const contents = approved.bom ? ["\uFEFF", approved.fixed] : [approved.fixed];
  const url = URL.createObjectURL(new Blob(contents, {type:"text/plain;charset=utf-8"}));
  const link = document.createElement("a");
  link.href = url;
  link.download = approved.filename.split(/[\\/]/).pop() || "fixed_code.txt";
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
};

function addTurn(role, text) {
  if (!history.length) el("messages").replaceChildren();
  const turn = node("div", "", "turn");
  turn.append(node("strong", role === "user" ? "You" : "DevPilot"), document.createTextNode(text));
  el("messages").append(turn);
  el("messages").scrollTop = el("messages").scrollHeight;
  history.push({role, text: text.slice(0, 4000)});
}
el("chatForm").onsubmit = async event => {
  event.preventDefault();
  const question = el("question").value.trim();
  if (!reviewed || !question || el("send").disabled) return;
  const current = version;
  el("send").disabled = true;
  el("chatStatus").textContent = "Thinking…";
  try {
    const response = await post("/chat", {...reviewed, question, history: history.slice(-8)});
    if (current !== version) return;
    addTurn("user", question);
    addTurn("assistant", response.answer);
    if (el("question").value.trim() === question) el("question").value = "";
    el("chatStatus").textContent = "";
  } catch (err) { if (current === version) el("chatStatus").textContent = err.message; }
  finally { if (current === version) el("send").disabled = false; }
};
