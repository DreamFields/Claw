#!/usr/bin/env node
/**
 * Start the markdown-upload-to-notion server and wait for it to be ready.
 * 
 * Usage:
 *   node start_server.js [--dir <server-dir>] [--port <port>]
 * 
 * Arguments:
 *   --dir   Path to the markdown-upload-to-notion project directory
 *           Default: C:\Users\vinmeng\WorkBuddy\markdown-upload-to-notion
 *   --port  Server port (default: 3000)
 */

const { spawn } = require('child_process');
const http = require('http');
const path = require('path');

function parseArgs() {
    const args = process.argv.slice(2);
    const parsed = {};
    for (let i = 0; i < args.length; i += 2) {
        const key = args[i].replace(/^--/, '');
        parsed[key] = args[i + 1];
    }
    return parsed;
}

const args = parseArgs();
const SERVER_DIR = args.dir || 'C:\\Users\\vinmeng\\WorkBuddy\\markdown-upload-to-notion';
const PORT = args.port || '3000';

function checkHealth(port, retries = 10, interval = 1000) {
    return new Promise((resolve, reject) => {
        let attempts = 0;
        const tryConnect = () => {
            attempts++;
            http.get(`http://localhost:${port}/api/health`, (res) => {
                let data = '';
                res.on('data', chunk => data += chunk);
                res.on('end', () => {
                    try {
                        const json = JSON.parse(data);
                        if (json.status === 'ok') {
                            resolve(true);
                        } else if (attempts < retries) {
                            setTimeout(tryConnect, interval);
                        } else {
                            reject(new Error('Health check returned non-ok status'));
                        }
                    } catch {
                        if (attempts < retries) setTimeout(tryConnect, interval);
                        else reject(new Error('Invalid health response'));
                    }
                });
            }).on('error', () => {
                if (attempts < retries) setTimeout(tryConnect, interval);
                else reject(new Error(`Server not ready after ${retries} attempts`));
            });
        };
        tryConnect();
    });
}

async function main() {
    // First check if server is already running
    try {
        await checkHealth(PORT, 1, 500);
        console.log(`[OK] Server already running on port ${PORT}`);
        process.exit(0);
    } catch {
        // Not running, start it
    }

    console.log(`Starting server from ${SERVER_DIR}...`);

    const serverProcess = spawn('node', ['server.js'], {
        cwd: SERVER_DIR,
        stdio: 'pipe',
        detached: true,
        env: { ...process.env, PORT }
    });

    serverProcess.stdout.on('data', (data) => {
        process.stdout.write(`[server] ${data}`);
    });

    serverProcess.stderr.on('data', (data) => {
        process.stderr.write(`[server:err] ${data}`);
    });

    serverProcess.unref();

    // Write PID for later cleanup
    console.log(`Server process started (PID: ${serverProcess.pid})`);

    try {
        await checkHealth(PORT, 15, 1000);
        console.log(`[OK] Server is ready at http://localhost:${PORT}`);
        process.exit(0);
    } catch (err) {
        console.error(`[ERROR] ${err.message}`);
        serverProcess.kill();
        process.exit(1);
    }
}

main();
