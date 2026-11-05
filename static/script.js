    const DEFAULT_VIDEO = "videoplayback.mp4";
    const $ = (id) => document.getElementById(id);
    const player = $("player"),
          streamImg = $("streamImg"),
          simCanvas = $("simCanvas"),
          canvas = $("canvas"),
          ctx = canvas.getContext("2d");

    let currentFilename = DEFAULT_VIDEO,
        points = [],
        confirmed = false,
        drawing = false,
        localUrl = null,
        statsTimer = null,
        simAnim = null,
        isDemoMode = false,
        enteredPeople = [],
        historyEntries = [],
        imageViewerPeople = [],
        imageViewerIndex = 0,
        playbackPaused = false,
        streamActive = false,
        historyPage = 1,
        historyPageSize = 8,
        historyTotal = 0,
        historyServerPaginated = false;

    function setStatus(t) { $("status").textContent = t; }

    function formatVideoTime(seconds) {
      if (!Number.isFinite(seconds) || seconds < 0) return "--:--";
      const wholeSeconds = Math.floor(seconds);
      const hours = Math.floor(wholeSeconds / 3600);
      const minutes = Math.floor((wholeSeconds % 3600) / 60);
      const remainder = wholeSeconds % 60;
      return hours
        ? `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`
        : `${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`;
    }

    function updateAnalysisProgress(positionSeconds, durationSeconds, visible = true) {
      const duration = Number.isFinite(durationSeconds) && durationSeconds > 0 ? durationSeconds : 0;
      const position = Number.isFinite(positionSeconds) && positionSeconds > 0 ? positionSeconds : 0;
      const percentage = duration ? Math.min(100, position / duration * 100) : 0;
      $("analysisElapsed").textContent = formatVideoTime(position);
      $("analysisDuration").textContent = formatVideoTime(duration);
      $("analysisProgressFill").style.width = `${percentage}%`;
      $("analysisProgress").setAttribute("aria-valuenow", String(Math.round(percentage)));
      $("analysisProgress").classList.toggle("show", visible);
    }

    function setPlaybackButton(paused) {
      playbackPaused = paused;
      $("playback").innerHTML = paused
        ? '<svg><use href="#play" /></svg>Tiếp tục'
        : '<svg><use href="#pause" /></svg>Tạm dừng';
    }

    // Khởi tạo video mặc định (Nếu không có backend sẽ bật Demo Canvas để bạn test ngay)
    async function loadDefault() {
      streamImg.style.display = "none";
      simCanvas.style.display = "none";
      player.style.display = "block";
      try {
        const res = await fetch("/api/default-video");
        if (res.ok) {
          const data = await res.json();
          currentFilename = data.filename || DEFAULT_VIDEO;
          player.src = data.url || ("/videos/" + encodeURIComponent(currentFilename));
          isDemoMode = false;
          await loadVideos(currentFilename);
          return;
        }
      } catch (e) {}
      // Nếu mở file trực tiếp chưa bật Flask -> Bật nền Demo
      isDemoMode = true;
      player.style.display = "none";
      simCanvas.style.display = "block";
      drawDemoIdle();
    }

    function fit() {
      const r = $("screenBox").getBoundingClientRect(),
            d = window.devicePixelRatio || 1;
      canvas.width = r.width * d;
      canvas.height = r.height * d;
      ctx.setTransform(d, 0, 0, d, 0, 0);
      simCanvas.width = r.width;
      simCanvas.height = r.height;
      paint();
      if (isDemoMode && !simAnim) drawDemoIdle();
    }

    // Vẽ đa giác ROI trên Canvas
    function paint() {
      const r = $("screenBox").getBoundingClientRect();
      ctx.clearRect(0, 0, r.width, r.height);
      if (!points.length) return;
      ctx.beginPath();
      points.forEach((p, i) =>
        i ? ctx.lineTo(p.x * r.width, p.y * r.height)
          : ctx.moveTo(p.x * r.width, p.y * r.height)
      );
      if (points.length >= 3) {
        ctx.closePath();
        ctx.fillStyle = "rgba(8, 169, 87, 0.22)";
        ctx.fill();
      }
      ctx.strokeStyle = "#00c864";
      ctx.lineWidth = 3;
      ctx.stroke();

      points.forEach((p) => {
        ctx.beginPath();
        ctx.arc(p.x * r.width, p.y * r.height, 5, 0, Math.PI * 2);
        ctx.fillStyle = "#fff";
        ctx.fill();
        ctx.strokeStyle = "#00c864";
        ctx.lineWidth = 2.5;
        ctx.stroke();
      });
    }

    function drawingMode(v) {
      drawing = v;
      canvas.style.pointerEvents = v ? "auto" : "none";
      canvas.style.cursor = v ? "crosshair" : "default";
      $("tools").classList.toggle("show", v);
      $("draw").disabled = v;
    }

    function roiStatus() {
      if (confirmed) {
        $("roiLabel").textContent = "● ROI Đang hoạt động";
        $("roiLabel").style.color = "#4ade80";
      } else {
        $("roiLabel").textContent = "● Chưa thiết lập ROI";
        $("roiLabel").style.color = "#ffffff";
      }
      $("start").disabled = !confirmed;
    }

    // Chọn video từ máy
    $("choose").onclick = () => $("file").click();
    $("file").onchange = async (e) => {
      const f = e.target.files[0];
      if (!f) return;
      try {
        await stopAllStreams();
      } catch (error) {
        setStatus(error.message || "Không thể dừng phân tích hiện tại.");
        return;
      }
      if (localUrl) URL.revokeObjectURL(localUrl);
      localUrl = URL.createObjectURL(f);
      simCanvas.style.display = "none";
      streamImg.style.display = "none";
      player.style.display = "block";
      player.src = localUrl;
      currentFilename = f.name;
      updateAnalysisProgress(0, 0, false);
      points = [];
      confirmed = false;
      enteredPeople = [];
      renderThumbnails();
      paint();
      roiStatus();
      setStatus("Đã chọn video");

      const fd = new FormData();
      fd.append("video", f);
      try {
        const r = await fetch("/api/upload", { method: "POST", body: fd });
        if (r.ok) {
          const d = await r.json();
          if (d.filename) currentFilename = d.filename;
          await loadVideos(currentFilename);
          isDemoMode = false;
        }
      } catch (err) {
        isDemoMode = true;
      }
    };

    $("videoSelect").onchange = async () => {
      const selected = $("videoSelect").value;
      if (!selected) return;
      try {
        await stopAllStreams();
      } catch (error) {
        setStatus(error.message || "Không thể dừng phân tích hiện tại.");
        return;
      }
      if (localUrl) { URL.revokeObjectURL(localUrl); localUrl = null; }
      currentFilename = selected;
      player.style.display = "block";
      streamImg.style.display = "none";
      simCanvas.style.display = "none";
      player.src = `/videos/${encodeURIComponent(selected)}`;
      player.load();
      updateAnalysisProgress(0, 0, false);
      points = [];
      confirmed = false;
      enteredPeople = [];
      renderThumbnails();
      paint();
      roiStatus();
      isDemoMode = false;
      setStatus("Đã chọn video");
    };

    async function loadVideos(selectedFilename = currentFilename) {
      const response = await fetch("/api/videos");
      if (!response.ok) throw new Error("Không tải được danh sách video.");
      const data = await response.json();
      const select = $("videoSelect");
      select.replaceChildren();
      (data.videos || []).forEach(video => {
        const option = document.createElement("option");
        option.value = video.filename;
        option.textContent = video.filename;
        select.appendChild(option);
      });
      if (!select.options.length) {
        const option = document.createElement("option");
        option.value = "";
        option.textContent = "Chưa có video";
        select.appendChild(option);
        currentFilename = "";
        return;
      }
      const match = [...select.options].find(option => option.value === selectedFilename);
      select.value = match ? selectedFilename : select.options[0].value;
      if (select.value !== currentFilename || !player.src) select.dispatchEvent(new Event("change"));
    }

    // Các nút Vẽ, Xóa, Hủy, Xác nhận ROI
    $("draw").onclick = () => {
      points = [];
      confirmed = false;
      paint();
      roiStatus();
      drawingMode(true);
      setStatus("Đang vẽ vùng ROI...");
    };

    canvas.onclick = (e) => {
      if (!drawing) return;
      const r = canvas.getBoundingClientRect();
      points.push({
        x: (e.clientX - r.left) / r.width,
        y: (e.clientY - r.top) / r.height,
      });
      paint();
    };

    $("clear").onclick = () => {
      points = [];
      confirmed = false;
      paint();
      roiStatus();
    };

    $("cancel").onclick = () => {
      points = [];
      confirmed = false;
      paint();
      drawingMode(false);
      roiStatus();
      setStatus("Sẵn sàng");
    };

    $("confirm").onclick = () => {
      if (points.length < 3) {
        alert("Vùng ROI cần ít nhất 3 điểm! Vui lòng chấm thêm điểm trên video.");
        return;
      }
      confirmed = true;
      drawingMode(false);
      paint();
      roiStatus();
      setStatus("ROI đã xác nhận - Sẵn sàng đếm");
    };

    // Bắt đầu đếm (Kết nối Flask hoặc chạy giả lập nếu xem trước)
    $("start").onclick = async () => {
      if (!confirmed || points.length < 3) return;
      $("start").disabled = true;
      enteredPeople = [];
      renderThumbnails();
      updateUIStats(0, 0, 0);
      $("playback").disabled = true;
      $("stop").disabled = true;
      setStatus("Đang chạy");
      updateAnalysisProgress(0, 0);

      const roi = points.map((p) => [+p.x.toFixed(5), +p.y.toFixed(5)]);
      try {
        const r = await fetch("/api/process", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ filename: currentFilename, roi }),
        });
        const d = await r.json();
        if (!r.ok) throw Error(d.error || "Không xử lý được video");

        // Nếu backend trả về MJPEG stream (main.py mới)
        if (d.status === "ok") {
          player.pause();
          player.style.display = "none";
          simCanvas.style.display = "none";
          streamImg.style.display = "block";
          streamImg.src = `/video_feed/${encodeURIComponent(currentFilename)}?t=${Date.now()}`;
          streamActive = true;
          $("overlayStats").classList.add("show");
          $("playback").disabled = false;
          $("stop").disabled = true;
          setPlaybackButton(false);
          // Tắt nét vẽ canvas đè lên vì backend đã vẽ sẵn ROI lên frame
          ctx.clearRect(0, 0, canvas.width, canvas.height);

          if (statsTimer) clearInterval(statsTimer);
          statsTimer = setInterval(async () => {
            try {
              const sr = await fetch("/api/stats");
              if (sr.ok) {
                const s = await sr.json();
                updateUIStats(s.count_in || 0, s.count_out || 0, s.total_people || 0);
                syncEnteredPeople(s.entered_people || []);
                updateAnalysisProgress(s.position_seconds || 0, s.duration_seconds || 0);
                $("stop").disabled = !s.running;
                if (s.paused !== playbackPaused) setPlaybackButton(!!s.paused);
                if (!s.running && (s.finalized || s.save_error)) {
                  updateAnalysisProgress(s.position_seconds || 0, s.duration_seconds || 0);
                  streamActive = false;
                  $("playback").disabled = true;
                  $("stop").disabled = true;
                  if (statsTimer) { clearInterval(statsTimer); statsTimer = null; }
                  setStatus(s.save_error || (s.completed ? "Phân tích hoàn tất" : "Đã dừng và lưu kết quả"));
                  await loadHistory();
                }
              }
            } catch (e) {}
          }, 800);
        } else if (d.output_url) {
          // Nếu backend trả về file video đã xử lý
          streamImg.style.display = "none";
          player.style.display = "block";
          player.src = d.output_url;
          player.load();
          await player.play().catch(() => {});
          updateUIStats(d.count_in || 0, d.count_out || 0, d.total_people || 0);
          await loadHistory();
        }
      } catch (err) {
        // Tự động chuyển sang Demo trực quan khi chạy thử không có Backend
        isDemoMode = true;
        streamActive = false;
        startInteractiveDemo();
      }
    };

    $("stop").onclick = async () => {
      $("stop").disabled = true;
      setStatus("Đang dừng và lưu kết quả...");
      try {
        const response = await fetch("/api/stop", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ save: true })
        });
        const result = await response.json();
        if (!response.ok && response.status !== 202) {
          if (result.stats) {
            streamActive = false;
            $("playback").disabled = true;
            if (statsTimer) { clearInterval(statsTimer); statsTimer = null; }
          }
          throw new Error(result.error || "Không thể dừng video.");
        }
        if (result.stats) {
          updateUIStats(
            result.stats.count_in || 0,
            result.stats.count_out || 0,
            result.stats.total_people || 0
          );
        }
        if (result.saved) {
          streamActive = false;
          streamImg.src = "";
          if (statsTimer) { clearInterval(statsTimer); statsTimer = null; }
          $("playback").disabled = true;
          await loadHistory();
          setStatus("Đã dừng và lưu kết quả");
        } else {
          setStatus("Đang dừng video...");
        }
      } catch (error) {
        $("stop").disabled = !streamActive;
        setStatus(error.message || "Không thể dừng video.");
      }
    };

    $("playback").onclick = async () => {
      if (isDemoMode) {
        if (localUrl && player.style.display !== "none") {
          if (playbackPaused) player.play().catch(() => {});
          else player.pause();
        }
        if (playbackPaused) {
          setPlaybackButton(false);
          startDemoAnimation();
        } else {
          setPlaybackButton(true);
          if (simAnim) { cancelAnimationFrame(simAnim); simAnim = null; }
        }
        return;
      }
      if (!streamActive) return;
      const endpoint = playbackPaused ? "/api/resume" : "/api/pause";
      try {
        const response = await fetch(endpoint, { method: "POST" });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || "Không thể điều khiển video.");
        setPlaybackButton(result.paused);
        setStatus(result.paused ? "Đã tạm dừng" : "Đang chạy");
      } catch (error) {
        setStatus(error.message || "Không thể điều khiển video.");
      }
    };

    function updateUIStats(inn, out, total) {
      const prevIn = parseInt($("inCount").textContent) || 0;
      $("inCount").textContent = inn;
      $("outCount").textContent = out;
      $("peopleCount").textContent = total;
      $("overlayInCount").textContent = inn;
      $("overlayOutCount").textContent = out;

      if (isDemoMode && inn > prevIn) {
        for (let i = prevIn + 1; i <= inn; i++) {
          addPersonThumbnail(i);
        }
      }
    }

    function syncEnteredPeople(people) {
      enteredPeople = people.map(person => ({
        id: person.id,
        time: person.time,
        img: person.image_url
      }));
      renderThumbnails();
    }

    // Tạo ảnh đại diện người vào ROI
    function makeAvatarSVG(id) {
      const colors = ["#2563eb", "#1f2937", "#6b7280", "#059669", "#7c3aed"];
      const c = colors[id % colors.length];
      const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="120" height="160" viewBox="0 0 120 160">
        <rect width="120" height="160" fill="#e2e8f0"/>
        <circle cx="60" cy="48" r="20" fill="#fbd38d"/>
        <path d="M32 145 C32 95 88 95 88 145 Z" fill="${c}"/>
        <rect x="8" y="8" width="42" height="20" rx="4" fill="rgba(0,0,0,0.6)"/>
        <text x="29" y="22" font-size="11" fill="#fff" font-family="sans-serif" text-anchor="middle" font-weight="bold">ID ${id}</text>
      </svg>`;
      return "data:image/svg+xml;utf8," + encodeURIComponent(svg);
    }

    function addPersonThumbnail(id) {
      const now = new Date().toTimeString().slice(0, 5);
      const item = { id, time: now, img: makeAvatarSVG(id) };
      enteredPeople.unshift(item);
      renderThumbnails();
    }

    function renderThumbnails() {
      const box = $("entered");
      if (!enteredPeople.length) {
        box.innerHTML = '<div class="empty">Chưa có dữ liệu</div>';
        return;
      }
      const visiblePeople = enteredPeople.slice(0, 5);
      box.innerHTML = visiblePeople.map((p, index) => `
        <div class="thumb selectable" role="button" tabindex="0" aria-label="Xem ảnh ID ${p.id}">
          <img src="${p.img}" alt="ID ${p.id}" />
          <b>ID ${p.id}</b>
          <small>${p.time}</small>
        </div>
      `).join("");
      bindImagePreview(box, visiblePeople, enteredPeople);
    }

    function bindImagePreview(container, people, viewerPeople = people) {
      container.querySelectorAll(".thumb").forEach((card, index) => {
        const openImage = () => showCapturedImage(viewerPeople, viewerPeople.indexOf(people[index]));
        card.onclick = openImage;
        card.onkeydown = (event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            openImage();
          }
        };
      });
    }

    function showCapturedImage(people, index) {
      if (index < 0 || index >= people.length) return;
      const person = people[index];
      if (!(person.img || person.image_url)) return;
      imageViewerPeople = people;
      imageViewerIndex = index;
      renderViewerImage();
      $("imageViewer").classList.add("show");
    }

    function renderViewerImage() {
      const person = imageViewerPeople[imageViewerIndex];
      if (!person) return;
      const imageUrl = person.img || person.image_url;
      if (!imageUrl) return;
      $("imageViewerImage").src = imageUrl;
      $("imageViewerTitle").textContent = `Ảnh đã chụp - ID ${person.id}`;
      $("imageViewerCaption").textContent = person.time || "";
      $("previousImage").disabled = imageViewerIndex === 0;
      $("nextImage").disabled = imageViewerIndex === imageViewerPeople.length - 1;
    }

    function closeImageViewer() {
      $("imageViewer").classList.remove("show");
      $("imageViewerImage").removeAttribute("src");
      imageViewerPeople = [];
      imageViewerIndex = 0;
    }

    function toHistoryDateParam(value) {
      const match = value.match(/^(\d{2})\/(\d{2})\/(\d{4})$/);
      if (!match) return "";
      const [, day, month, year] = match;
      const parsed = new Date(Number(year), Number(month) - 1, Number(day));
      if (parsed.getFullYear() !== Number(year) || parsed.getMonth() !== Number(month) - 1 || parsed.getDate() !== Number(day)) return "";
      return `${year}-${month}-${day}`;
    }

    async function loadHistory(page = 1) {
      try {
        const params = new URLSearchParams();
        params.set("page", String(page));
        const selectedDate = $("historyDate").value.trim();
        const dateParam = selectedDate ? toHistoryDateParam(selectedDate) : "";
        if (selectedDate && !dateParam) {
          setStatus("Ngày phải theo định dạng dd/mm/yyyy.");
          return;
        }
        if (dateParam) params.set("date", dateParam);
        const query = params.toString();
        const suffix = query ? `?${query}` : "";
        const response = await fetch(`/api/history${suffix}`);
        if (!response.ok) throw new Error("Không tải được lịch sử phân tích.");
        const data = await response.json();
        historyEntries = data.history || [];
        historyServerPaginated = Number.isInteger(data.total);
        historyTotal = historyServerPaginated ? data.total : historyEntries.length;
        historyPage = data.page || page;
        historyPageSize = data.per_page || 8;
        renderHistory();
      } catch (error) {
        setStatus(error.message || "Không tải được lịch sử phân tích.");
      }
    }

    function renderHistory() {
      const body = $("historyBody");
      body.replaceChildren();
      const visibleEntries = historyServerPaginated
        ? historyEntries
        : historyEntries.slice((historyPage - 1) * historyPageSize, historyPage * historyPageSize);
      if (!visibleEntries.length) {
        body.innerHTML = '<tr><td colspan="8" class="empty">Chưa có lịch sử phân tích</td></tr>';
        $("historyPagination").replaceChildren();
        return;
      }
      const firstRowNumber = (historyPage - 1) * historyPageSize + 1;
      visibleEntries.forEach((entry, index) => {
        const row = document.createElement("tr");
        [
          firstRowNumber + index,
          entry.filename,
          entry.created_at,
          entry.total_people || 0,
          entry.count_in || 0,
          entry.count_out || 0
        ].forEach((value, cellIndex) => {
          const cell = document.createElement("td");
          cell.textContent = value;
          if (cellIndex === 1) cell.style.fontWeight = "600";
          if (cellIndex === 2) cell.style.color = "var(--muted)";
          if (cellIndex === 4) cell.style.cssText = "color:#07984d;font-weight:700";
          if (cellIndex === 5) cell.style.cssText = "color:#e53b3b;font-weight:700";
          row.appendChild(cell);
        });
        const statusCell = document.createElement("td");
        statusCell.innerHTML = '<span class="badge">Hoàn thành</span>';
        row.appendChild(statusCell);
        const actionCell = document.createElement("td");
        const detailButton = document.createElement("button");
        detailButton.className = "btn-detail";
        detailButton.innerHTML = '<svg style="width:15px;height:15px"><use href="#search"/></svg>Xem chi tiết';
        detailButton.onclick = () => openDetailModal(entry);
        actionCell.appendChild(detailButton);
        row.appendChild(actionCell);
        body.appendChild(row);
      });
      renderHistoryPagination();
    }

    function renderHistoryPagination() {
      const pagination = $("historyPagination");
      pagination.replaceChildren();
      const totalPages = Math.ceil(historyTotal / historyPageSize);
      if (totalPages <= 1) return;

      const addButton = (label, page, options = {}) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = `page-button${options.active ? " active" : ""}`;
        button.textContent = label;
        button.disabled = !!options.disabled;
        if (options.label) button.setAttribute("aria-label", options.label);
        if (options.active) button.setAttribute("aria-current", "page");
        button.onclick = () => loadHistory(page);
        pagination.appendChild(button);
      };

      addButton("‹", Math.max(1, historyPage - 1), {
        disabled: historyPage === 1,
        label: "Trang trước",
      });

      const visiblePages = new Set([1, totalPages]);
      for (let page = Math.max(1, historyPage - 1); page <= Math.min(totalPages, historyPage + 1); page++) {
        visiblePages.add(page);
      }
      let previousPage = 0;
      [...visiblePages].sort((a, b) => a - b).forEach(page => {
        if (previousPage && page - previousPage > 1) {
          const ellipsis = document.createElement("span");
          ellipsis.className = "page-ellipsis";
          ellipsis.textContent = "…";
          pagination.appendChild(ellipsis);
        }
        addButton(String(page), page, { active: page === historyPage });
        previousPage = page;
      });

      addButton("›", Math.min(totalPages, historyPage + 1), {
        disabled: historyPage === totalPages,
        label: "Trang sau",
      });
    }

    // Mở / Đóng Modal Chi tiết phân tích
    window.openDetailModal = function(entry = null) {
      const people = entry?.entered_people || enteredPeople;
      $("modalIn").textContent = entry?.count_in ?? $("inCount").textContent;
      $("modalOut").textContent = entry?.count_out ?? $("outCount").textContent;
      $("modalTotal").textContent = entry?.total_people ?? $("peopleCount").textContent;
      $("modalBadgeTotal").textContent = `Tổng: ${$("modalTotal").textContent} người`;

      const list = $("modalPeopleList");
      if (!people.length) {
        list.innerHTML = '<div class="empty">Chưa có dữ liệu người vào ROI</div>';
      } else {
        list.innerHTML = people.map(p => `
          <div class="thumb selectable" role="button" tabindex="0" aria-label="Xem ảnh ID ${p.id}">
            <img src="${p.img || p.image_url}" alt="ID ${p.id}" tabindex="0" />
            <b>ID ${p.id}</b>
            <small>${p.time}</small>
          </div>
        `).join("");
        bindImagePreview(list, people);
      }
      $("detailModal").classList.add("show");
    };

    $("openModalLink").onclick = () => openDetailModal();
    $("closeModalX").onclick = () => $("detailModal").classList.remove("show");
    $("closeModalBtn").onclick = () => $("detailModal").classList.remove("show");
    $("closeImageViewer").onclick = closeImageViewer;
    $("previousImage").onclick = () => {
      if (imageViewerIndex > 0) {
        imageViewerIndex--;
        renderViewerImage();
      }
    };
    $("nextImage").onclick = () => {
      if (imageViewerIndex < imageViewerPeople.length - 1) {
        imageViewerIndex++;
        renderViewerImage();
      }
    };
    $("filterHistory").onclick = () => loadHistory(1);
    $("historyDate").onchange = () => loadHistory(1);
    $("historyDatePickerButton").onclick = () => {
      const picker = $("historyDatePicker");
      if (picker.showPicker) picker.showPicker();
      else picker.click();
    };
    $("historyDatePicker").onchange = (event) => {
      const [year, month, day] = event.target.value.split("-");
      if (!year) return;
      $("historyDate").value = `${day}/${month}/${year}`;
      loadHistory(1);
    };
    $("imageViewer").onclick = (event) => {
      if (event.target === $("imageViewer")) closeImageViewer();
    };
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        closeImageViewer();
        $("detailModal").classList.remove("show");
      } else if ($("imageViewer").classList.contains("show") && event.key === "ArrowLeft") {
        $("previousImage").click();
      } else if ($("imageViewer").classList.contains("show") && event.key === "ArrowRight") {
        $("nextImage").click();
      }
    });

    async function stopAllStreams() {
      if (statsTimer) { clearInterval(statsTimer); statsTimer = null; }
      if (simAnim) { cancelAnimationFrame(simAnim); simAnim = null; }
      const response = await fetch("/api/stop", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ save: false }),
      });
      const result = await response.json();
      if (!response.ok || result.status === "stopping") {
        throw new Error(result.error || "Không thể dừng phân tích để thiết lập lại.");
      }
      streamActive = false;
      streamImg.src = "";
      streamImg.style.display = "none";
      player.style.display = "block";
      $("overlayStats").classList.remove("show");
      $("playback").disabled = true;
      setPlaybackButton(false);
    }

    // Nút Thiết lập lại (Reset)
    $("reset").onclick = async () => {
      const resetButton = $("reset");
      resetButton.disabled = true;
      setStatus("Đang thiết lập lại...");
      try {
        await stopAllStreams();
        player.pause();
        points = [];
        confirmed = false;
        enteredPeople = [];
        updateAnalysisProgress(0, 0, false);
        updateUIStats(0, 0, 0);
        drawingMode(false);
        paint();
        roiStatus();
        $("stop").disabled = true;
        renderThumbnails();
        await loadDefault();
        await loadHistory(1);
        setStatus("Đã thiết lập lại");
      } catch (error) {
        setStatus(error.message || "Không thể thiết lập lại.");
      } finally {
        resetButton.disabled = false;
      }
    };

    /* =========================================================================
       CHẾ ĐỘ DEMO TRỰC QUAN (Chạy khi mở file trực tiếp chưa bật Server Flask)
       ========================================================================= */
    function drawDemoIdle() {
      const sctx = simCanvas.getContext("2d");
      const w = simCanvas.width, h = simCanvas.height;
      sctx.fillStyle = "#1e293b";
      sctx.fillRect(0, 0, w, h);
      sctx.strokeStyle = "rgba(255,255,255,0.06)";
      for (let x = 0; x < w; x += 45) { sctx.beginPath(); sctx.moveTo(x, 0); sctx.lineTo(x, h); sctx.stroke(); }
      for (let y = 0; y < h; y += 45) { sctx.beginPath(); sctx.moveTo(0, y); sctx.lineTo(w, y); sctx.stroke(); }
      sctx.fillStyle = "#94a3b8";
      sctx.font = "600 15px Segoe UI, sans-serif";
      sctx.textAlign = "center";
      sctx.fillText("Màn hình mô phỏng Camera (Hãy bấm 'Vẽ ROI' -> Chấm 3 điểm -> 'Xác nhận' -> 'Bắt đầu đếm')", w / 2, h / 2);
    }

    function pointInPoly(x, y, poly) {
      let inside = false;
      for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
        const xi = poly[i].x, yi = poly[i].y;
        const xj = poly[j].x, yj = poly[j].y;
        const intersect = ((yi > y) !== (yj > y)) && (x < (xj - xi) * (y - yi) / (yj - yi + 0.00001) + xi);
        if (intersect) inside = !inside;
      }
      return inside;
    }

    function startInteractiveDemo() {
      if (localUrl && player.style.display !== "none") {
        player.play().catch(() => {});
      } else {
        player.style.display = "none";
        simCanvas.style.display = "block";
      }
      const sctx = simCanvas.getContext("2d");
      const agents = Array.from({ length: 8 }, (_, i) => ({
        id: i + 1,
        x: Math.random() * 0.8 + 0.1,
        y: Math.random() * 0.8 + 0.1,
        vx: (Math.random() - 0.5) * 0.0035,
        vy: (Math.random() - 0.5) * 0.0035,
        inRoi: false
      }));
      let cIn = 0, cOut = 0, totalIds = agents.length;

      function step() {
        const w = simCanvas.width, h = simCanvas.height;
        if (simCanvas.style.display !== "none") {
          sctx.fillStyle = "#1e293b";
          sctx.fillRect(0, 0, w, h);
          sctx.strokeStyle = "rgba(255,255,255,0.06)";
          for (let x = 0; x < w; x += 45) { sctx.beginPath(); sctx.moveTo(x, 0); sctx.lineTo(x, h); sctx.stroke(); }
          for (let y = 0; y < h; y += 45) { sctx.beginPath(); sctx.moveTo(0, y); sctx.lineTo(w, y); sctx.stroke(); }
        }
        paint();

        agents.forEach(a => {
          a.x += a.vx; a.y += a.vy;
          if (a.x < 0.05 || a.x > 0.95) a.vx *= -1;
          if (a.y < 0.08 || a.y > 0.92) a.vy *= -1;

          const inside = pointInPoly(a.x, a.y, points);
          if (inside && !a.inRoi) {
            a.inRoi = true; cIn++;
            updateUIStats(cIn, cOut, totalIds);
          } else if (!inside && a.inRoi) {
            a.inRoi = false; cOut++;
            updateUIStats(cIn, cOut, totalIds);
          }

          const px = a.x * w, py = a.y * h;
          const bw = 34, bh = 58;
          ctx.strokeStyle = inside ? "#00e676" : "#3b82f6";
          ctx.lineWidth = 2;
          ctx.strokeRect(px - bw / 2, py - bh / 2, bw, bh);
          ctx.fillStyle = inside ? "#00e676" : "#3b82f6";
          ctx.fillRect(px - bw / 2, py - bh / 2 - 18, 86, 18);
          ctx.fillStyle = "#fff";
          ctx.font = "bold 11px sans-serif";
          ctx.fillText(`ID ${a.id}`, px - bw / 2 + 4, py - bh / 2 - 5);
        });

        simAnim = requestAnimationFrame(step);
      }
      startDemoAnimation();

      function startDemoAnimation() {
        if (!simAnim) simAnim = requestAnimationFrame(step);
      }
    }

    window.addEventListener("resize", fit);
    player.addEventListener("loadedmetadata", fit);
    loadDefault();
    loadHistory();
    fit();
    roiStatus();
