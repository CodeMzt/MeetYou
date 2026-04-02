"use strict";
const electron = require("electron");
const path = require("node:path");
process.env.DIST = path.join(__dirname, "../dist");
process.env.VITE_PUBLIC = electron.app.isPackaged ? process.env.DIST : path.join(process.env.DIST, "../public");
let win;
let dashboardWin = null;
let settingsWin = null;
const VITE_DEV_SERVER_URL = process.env["VITE_DEV_SERVER_URL"];
function createSettingsWindow() {
  if (settingsWin) {
    if (settingsWin.isMinimized()) settingsWin.restore();
    settingsWin.focus();
    return;
  }
  const primaryDisplay = electron.screen.getPrimaryDisplay();
  const { width, height } = primaryDisplay.workAreaSize;
  const windowWidth = 680;
  const windowHeight = 760;
  settingsWin = new electron.BrowserWindow({
    width: windowWidth,
    height: windowHeight,
    x: width / 2 - windowWidth / 2,
    y: height / 2 - windowHeight / 2,
    icon: path.join(process.env.VITE_PUBLIC, "electron-vite.svg"),
    transparent: true,
    frame: false,
    resizable: true,
    minWidth: 560,
    minHeight: 620,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      nodeIntegration: false,
      contextIsolation: true
    }
  });
  if (process.platform === "win32") {
    settingsWin.setBackgroundMaterial("mica");
  } else if (process.platform === "darwin") {
    settingsWin.setVibrancy("popover");
  }
  if (VITE_DEV_SERVER_URL) {
    settingsWin.loadURL(`${VITE_DEV_SERVER_URL}#/settings`);
  } else {
    settingsWin.loadFile(path.join(process.env.DIST, "index.html"), { hash: "settings" });
  }
  settingsWin.on("closed", () => {
    settingsWin = null;
  });
}
function createDashboardWindow() {
  if (dashboardWin) {
    if (dashboardWin.isMinimized()) dashboardWin.restore();
    dashboardWin.focus();
    return;
  }
  const primaryDisplay = electron.screen.getPrimaryDisplay();
  const { width, height } = primaryDisplay.workAreaSize;
  const windowWidth = 920;
  const windowHeight = 720;
  dashboardWin = new electron.BrowserWindow({
    width: windowWidth,
    height: windowHeight,
    x: width / 2 - windowWidth / 2,
    y: height / 2 - windowHeight / 2,
    icon: path.join(process.env.VITE_PUBLIC, "electron-vite.svg"),
    transparent: true,
    frame: false,
    resizable: true,
    minWidth: 840,
    minHeight: 620,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      nodeIntegration: false,
      contextIsolation: true
    }
  });
  if (process.platform === "win32") {
    dashboardWin.setBackgroundMaterial("mica");
  } else if (process.platform === "darwin") {
    dashboardWin.setVibrancy("popover");
  }
  if (VITE_DEV_SERVER_URL) {
    dashboardWin.loadURL(`${VITE_DEV_SERVER_URL}#/dashboard`);
  } else {
    dashboardWin.loadFile(path.join(process.env.DIST, "index.html"), { hash: "dashboard" });
  }
  dashboardWin.on("closed", () => {
    dashboardWin = null;
  });
}
function createWindow() {
  const primaryDisplay = electron.screen.getPrimaryDisplay();
  const { width, height } = primaryDisplay.workAreaSize;
  const windowWidth = 400;
  const windowHeight = 620;
  win = new electron.BrowserWindow({
    width: windowWidth,
    height: windowHeight,
    x: width - windowWidth - 20,
    y: height - windowHeight - 40,
    icon: path.join(process.env.VITE_PUBLIC, "electron-vite.svg"),
    transparent: true,
    frame: false,
    alwaysOnTop: true,
    resizable: true,
    minWidth: 340,
    minHeight: 460,
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
  electron.ipcMain.on("window-close", (e) => {
    const w = electron.BrowserWindow.fromWebContents(e.sender);
    w == null ? void 0 : w.close();
  });
  electron.ipcMain.on("window-minimize", (e) => {
    const w = electron.BrowserWindow.fromWebContents(e.sender);
    w == null ? void 0 : w.minimize();
  });
  electron.ipcMain.on("window-maximize", (e) => {
    const w = electron.BrowserWindow.fromWebContents(e.sender);
    if (w == null ? void 0 : w.isMaximized()) w.unmaximize();
    else w == null ? void 0 : w.maximize();
  });
  electron.ipcMain.on("window-toggle-top", (e, isTop) => {
    const w = electron.BrowserWindow.fromWebContents(e.sender);
    w == null ? void 0 : w.setAlwaysOnTop(isTop);
  });
  electron.ipcMain.on("open-dashboard", () => {
    createDashboardWindow();
  });
  electron.ipcMain.on("open-settings", () => {
    createSettingsWindow();
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
