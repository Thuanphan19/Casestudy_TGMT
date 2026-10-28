const input = document.getElementById("video-input");
const videoBox = document.getElementById("video-box");

let videoUrl = null;
let selectedFile = null;

input.addEventListener("change", () => {
  const file = input.files[0];

  if (!file) return;

  if (!file.type.startsWith("video/")) {
    document.getElementById("message").textContent =
      "Vui lòng chọn tệp video hợp lệ.";
    input.value = "";
    return;
  }

  selectedFile = file;

  if (videoUrl) URL.revokeObjectURL(videoUrl);
  videoUrl = URL.createObjectURL(file);

  const video = document.createElement("video");
  video.src = videoUrl;
  video.controls = true;
  video.preload = "metadata";

  video.addEventListener("loadedmetadata", () => {
    const seconds = Math.floor(video.duration || 0);
    const minutes = String(Math.floor(seconds / 60)).padStart(2, "0");
    const remainder = String(seconds % 60).padStart(2, "0");

    document.getElementById("video-time").textContent =
      `${minutes}:${remainder}`;
  });

  videoBox.replaceChildren(video);

  document.getElementById("video-name").textContent = file.name;
  document.getElementById("file-status").textContent = "Đã chọn video";
  document.getElementById("process-status").textContent = "Sẵn sàng";
  document.getElementById("message").textContent =
    "Video đã được chọn. Chưa kết nối YOLO.";
});

document.getElementById("start-btn").addEventListener("click", () => {
  document.getElementById("message").textContent = selectedFile
    ? "Video đã sẵn sàng. Thuật toán AI sẽ được tích hợp ở bước sau."
    : "Bạn cần chọn video trước.";
});

document.getElementById("reset-btn").addEventListener("click", () => {
  input.value = "";
  selectedFile = null;

  if (videoUrl) {
    URL.revokeObjectURL(videoUrl);
    videoUrl = null;
  }

  videoBox.innerHTML = `
        <div class="placeholder">
            <div class="play-icon">▶</div>
            <p>Video xem trước sẽ xuất hiện ở đây</p>
        </div>`;

  document.getElementById("video-name").textContent = "Chưa chọn video";
  document.getElementById("video-time").textContent = "00:00";
  document.getElementById("file-status").textContent = "Chưa có";
  document.getElementById("process-status").textContent = "Đang chờ";
  document.getElementById("message").textContent = "Đã đặt lại giao diện.";
  document.getElementById("progress-text").textContent = "0%";
  document.getElementById("progress-bar").style.width = "0%";

  document.getElementById("in-count").textContent = "0";
  document.getElementById("out-count").textContent = "0";
  document.getElementById("total-count").textContent = "0";
});

document.getElementById("export-btn").addEventListener("click", () => {
  const rows = [
    ["Chi so", "Gia tri"],
    ["Nguoi di vao", document.getElementById("in-count").textContent],
    ["Nguoi di ra", document.getElementById("out-count").textContent],
    ["Tong luot", document.getElementById("total-count").textContent],
    ["Trang thai", "Du lieu thu nghiem"],
  ];

  const csv =
    "\uFEFF" +
    rows
      .map((row) =>
        row
          .map((value) => `"${String(value).replaceAll('"', '""')}"`)
          .join(","),
      )
      .join("\r\n");

  const blob = new Blob([csv], {
    type: "text/csv;charset=utf-8;",
  });

  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");

  link.href = url;
  link.download = "bao_cao_thu_nghiem.csv";
  link.click();

  URL.revokeObjectURL(url);
});
