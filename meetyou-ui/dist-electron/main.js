"use strict";
const electron = require("electron");
const path = require("node:path");
process.env.DIST = path.join(__dirname, "../dist");
process.env.VITE_PUBLIC = electron.app.isPackaged ? process.env.DIST : path.join(process.env.DIST, "../public");
let win;
const VITE_DEV_SERVER_URL = process.env["VITE_DEV_SERVER_URL"];
function createWindow() {
  const primaryDisplay = electron.screen.getPrimaryDisplay();
  const { width, height } = primaryDisplay.workAreaSize;
  win = new electron.BrowserWindow({
    width: 360,
    height: 560,
    x: width - 380,
    y: height - 600,
    icon: path.join(process.env.VITE_PUBLIC, "electron-vite.svg"),
    transparent: true,
    frame: false,
    alwaysOnTop: true,
    resizable: true,
    minWidth: 300,
    minHeight: 400,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      // Needed for some local assets and modules
      nodeIntegration: false,
      contextIsolation: true
    }
  });
  if (process.platform === "win32") {
    win.setBackgroundMaterial("mica");
  } else if (process.platform === "darwin") {
    win.setVibrancy("popover");
  }
  if (VITE_DEV_SERVER_URL) {
    win.loadURL(VITE_DEV_SERVER_URL);
  } else {
    win.loadFile(path.join(process.env.DIST, "index.html"));
  }
  electron.ipcMain.on("window-close", () => win == null ? void 0 : win.close());
  electron.ipcMain.on("window-minimize", () => win == null ? void 0 : win.minimize());
  electron.ipcMain.on("window-toggle-top", (e, isTop) => {
    win == null ? void 0 : win.setAlwaysOnTop(isTop);
  });
}
electron.app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    electron.app.quit();
    win = null;
  }
});
electron.app.on("activate", () => {
  if (electron.BrowserWindow.getAllWindows().length === 0) {
    createWindow();
  }
});
electron.app.whenReady().then(createWindow);
