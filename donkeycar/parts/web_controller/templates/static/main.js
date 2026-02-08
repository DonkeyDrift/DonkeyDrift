var driveHandler = new function() {
    //functions used to drive the vehicle. 

    var state = {
        'tele': {
            "user": {
                'angle': 0,
                'throttle': 0,
            },
            "pilot": {
                'angle': 0,
                'throttle': 0,
            }
        },
        'brakeOn': true,
        'recording': false,
        'driveMode': "user",
        'pilot': 'None',
        'session': 'None',
        'lag': 0,
        'controlMode': 'joystick',
        'maxThrottle' : 1,
        'throttleMode' : 'user',
        'buttons': {
            "w1": false,  // boolean; true is 'down' or pushed, false is 'up' or not pushed
            "w2": false,
            "w3": false,
            "w4": false,
            "w5": false,
        },
        // 参数可通过滑块调整并持久化
        'params': {
            'pid': {
                'kp': 0.8,
                'ki': 0.0,
                'kd': 0.15,
            },
            'recenterRate': 0.35, // 每秒回中速度（角度/秒）
            'steerRate': 1.2,     // 左右方向键按下时角速度（角度/秒）
            'accelRate': 1.0,     // 每秒加速率（油门单位/秒）
            'brakeRate': 1.2      // 每秒减速/刹车率
        },
        // IKJL 按键状态（替代方向键，避免浏览器默认行为）
        'keyInput': {
            'left': false,   // J
            'right': false,  // L
            'up': false,     // I
            'down': false,   // K
        }
    }

    const PARAM_STORAGE_KEY = 'dkc_drive_params';
    const PARAM_VERSION = '2.0'; // 版本控制，用于数据迁移

    // 默认参数配置（用于重置和验证）
    const DEFAULT_PARAMS = {
        'pid': {
            'kp': 0.8,
            'ki': 0.0,
            'kd': 0.05,
        },
        'recenterRate': 0.35,
        'steerRate': 1.2,
        'accelRate': 1.0,
        'brakeRate': 1.2
    };

    var joystick_options = {}
    var joystickLoopRunning=false;

    var hasGamepad = false;

    var deviceHasOrientation=false;
    var initialGamma;

    var vehicle_id = ""
    var driveURL = ""
    var socket

    // ---------- 增强的参数持久化系统 ----------
    
    /**
     * 显示用户通知消息
     * @param {string} message - 消息内容
     * @param {string} type - 消息类型: 'success', 'error', 'warning', 'info'
     * @param {number} duration - 显示时长（毫秒），默认3000
     */
    var showNotification = function(message, type = 'info', duration = 3000) {
        // 创建或获取通知容器
        let container = document.getElementById('notification-container');
        if (!container) {
            container = document.createElement('div');
            container.id = 'notification-container';
            container.style.cssText = 'position:fixed;top:20px;right:20px;z-index:9999;max-width:350px;';
            document.body.appendChild(container);
        }

        // 创建通知元素
        const notification = document.createElement('div');
        const bgColors = {
            'success': '#28a745',
            'error': '#dc3545',
            'warning': '#ffc107',
            'info': '#17a2b8'
        };
        notification.style.cssText = `
            background: ${bgColors[type] || bgColors.info};
            color: white;
            padding: 15px 20px;
            margin-bottom: 10px;
            border-radius: 4px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            animation: slideIn 0.3s ease-out;
            font-size: 14px;
            word-wrap: break-word;
        `;
        notification.textContent = message;

        container.appendChild(notification);

        // 自动移除
        setTimeout(() => {
            notification.style.animation = 'slideOut 0.3s ease-out';
            setTimeout(() => {
                if (notification.parentNode) {
                    notification.parentNode.removeChild(notification);
                }
            }, 300);
        }, duration);
    };

    /**
     * 验证参数值的合法性
     * @param {object} params - 待验证的参数对象
     * @returns {boolean} 是否合法
     */
    var validateParams = function(params) {
        if (!params || typeof params !== 'object') return false;
        
        // 检查必需字段
        if (!params.pid || typeof params.pid !== 'object') return false;
        if (typeof params.pid.kp !== 'number' || params.pid.kp < 0 || params.pid.kp > 3) return false;
        if (typeof params.pid.ki !== 'number' || params.pid.ki < 0 || params.pid.ki > 1) return false;
        if (typeof params.pid.kd !== 'number' || params.pid.kd < 0 || params.pid.kd > 0.1) return false;
        
        if (typeof params.recenterRate !== 'number' || params.recenterRate < 0 || params.recenterRate > 2) return false;
        if (typeof params.steerRate !== 'number' || params.steerRate < 0 || params.steerRate > 3) return false;
        if (typeof params.accelRate !== 'number' || params.accelRate < 0 || params.accelRate > 3) return false;
        if (typeof params.brakeRate !== 'number' || params.brakeRate < 0 || params.brakeRate > 3) return false;
        
        return true;
    };

    /**
     * 从 localStorage 加载持久化参数
     * @returns {boolean} 是否成功加载
     */
    var loadPersistedParams = function() {
        try {
            const raw = localStorage.getItem(PARAM_STORAGE_KEY);
            if (!raw) {
                console.info('No saved parameters found, using defaults');
                return false;
            }

            const data = JSON.parse(raw);
            
            // 版本检查
            if (data.version !== PARAM_VERSION) {
                console.warn(`Parameter version mismatch: saved=${data.version}, current=${PARAM_VERSION}`);
                // 可以在此处实现数据迁移逻辑
            }

            // 验证参数
            if (!validateParams(data.params)) {
                console.error('Loaded parameters validation failed, using defaults');
                showNotification('加载的参数验证失败，已使用默认值', 'warning');
                return false;
            }

            // 更新状态
            updateState(state.params, data.params);
            
            console.info('Parameters loaded successfully:', data.params);
            showNotification('参数加载成功', 'success', 2000);
            return true;

        } catch (err) {
            console.error('Failed to load parameters:', err);
            showNotification('参数加载失败: ' + err.message, 'error');
            return false;
        }
    };

    /**
     * 保存参数到 localStorage
     * @returns {boolean} 是否成功保存
     */
    var savePersistedParams = function() {
        try {
            // 验证参数
            if (!validateParams(state.params)) {
                throw new Error('参数验证失败，无法保存');
            }

            const data = {
                version: PARAM_VERSION,
                timestamp: new Date().toISOString(),
                params: JSON.parse(JSON.stringify(state.params)) // 深拷贝
            };

            localStorage.setItem(PARAM_STORAGE_KEY, JSON.stringify(data));
            console.info('Parameters saved successfully');
            
            // 同时尝试保存到服务器
            saveParamsToServer();
            
            return true;

        } catch (err) {
            console.error('Failed to save parameters:', err);
            showNotification('参数保存失败: ' + err.message, 'error');
            return false;
        }
    };

    /**
     * 保存参数到服务器（异步）
     */
    var saveParamsToServer = function() {
        try {
            if (!socket || socket.readyState !== WebSocket.OPEN) {
                console.warn('WebSocket not connected, skipping server save');
                return;
            }

            const message = {
                msg_type: 'save_params',
                params: state.params,
                timestamp: new Date().toISOString()
            };

            socket.send(JSON.stringify(message));
            console.info('Parameters sent to server for persistence');

        } catch (err) {
            console.warn('Failed to save parameters to server:', err);
            // 不显示错误通知，因为本地已保存成功
        }
    };

    /**
     * 从服务器加载参数（通过 HTTP）
     */
    var loadParamsFromServer = function() {
        fetch('/api/get_params')
            .then(response => {
                if (!response.ok) throw new Error('Server returned ' + response.status);
                return response.json();
            })
            .then(data => {
                if (data.params && validateParams(data.params)) {
                    updateState(state.params, data.params);
                    applyParamsToUI();
                    showNotification('从服务器加载参数成功', 'success');
                    console.info('Parameters loaded from server:', data.params);
                }
            })
            .catch(err => {
                console.warn('Failed to load parameters from server:', err);
                // 使用本地存储的参数
            });
    };

    /**
     * 重置参数到默认值
     */
    var resetParams = function() {
        try {
            state.params = JSON.parse(JSON.stringify(DEFAULT_PARAMS));
            applyParamsToUI();
            savePersistedParams();
            showNotification('参数已重置为默认值', 'success');
            console.info('Parameters reset to defaults');
        } catch (err) {
            console.error('Failed to reset parameters:', err);
            showNotification('参数重置失败: ' + err.message, 'error');
        }
    };

    /**
     * 导出参数为 JSON 文件
     */
    var exportParams = function() {
        try {
            const data = {
                version: PARAM_VERSION,
                exportDate: new Date().toISOString(),
                params: state.params
            };

            const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `donkeycar-params-${new Date().toISOString().split('T')[0]}.json`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);

            showNotification('参数导出成功', 'success');
            console.info('Parameters exported');

        } catch (err) {
            console.error('Failed to export parameters:', err);
            showNotification('参数导出失败: ' + err.message, 'error');
        }
    };

    /**
     * 从 JSON 文件导入参数
     */
    var importParams = function(file) {
        const reader = new FileReader();
        
        reader.onload = function(e) {
            try {
                const data = JSON.parse(e.target.result);
                
                if (!data.params || !validateParams(data.params)) {
                    throw new Error('导入的文件格式无效或参数不合法');
                }

                state.params = JSON.parse(JSON.stringify(data.params));
                applyParamsToUI();
                savePersistedParams();
                
                showNotification('参数导入成功', 'success');
                console.info('Parameters imported:', data.params);

            } catch (err) {
                console.error('Failed to import parameters:', err);
                showNotification('参数导入失败: ' + err.message, 'error');
            }
        };

        reader.onerror = function() {
            showNotification('文件读取失败', 'error');
        };

        reader.readAsText(file);
    };

    // ---------- IKJL 增量控制循环（替代方向键）----------
    var lastArrowLoopTs = Date.now();

    var arrowControlActive = false;

    var arrowControlLoop = function() {
      setTimeout(function() {
        const now = Date.now();
        const dt = Math.max((now - lastArrowLoopTs) / 1000.0, 0.001);
        lastArrowLoopTs = now;
        let changed = false;
        const anyKey = state.keyInput.left || state.keyInput.right || state.keyInput.up || state.keyInput.down;

        if(anyKey) { 
          arrowControlActive = true;
          console.log('IKJL keys active:', state.keyInput);
        }
        if(!arrowControlActive) {
          arrowControlLoop();
          return;
        }

        // J/L 控制转向：按住时角度持续增加/减少
        if(state.keyInput.left && !state.keyInput.right) {
          state.tele.user.angle = Math.max(state.tele.user.angle - state.params.steerRate * dt, -1);
          changed = true;
        } else if(state.keyInput.right && !state.keyInput.left) {
          state.tele.user.angle = Math.min(state.tele.user.angle + state.params.steerRate * dt, 1);
          changed = true;
        } else {
          // 松开 J/L 时自动回中
          if(Math.abs(state.tele.user.angle) > 0.001) {
            const sign = Math.sign(state.tele.user.angle);
            const delta = state.params.recenterRate * dt;
            const next = state.tele.user.angle - sign * delta;
            // 过零保护
            state.tele.user.angle = (sign > 0) ? Math.max(next, 0) : Math.min(next, 0);
            changed = true;
          }
        }

        // PID 平滑：将目标角度误差通过 PID 修正（模拟竞速手感）
        const targetAngle = state.tele.user.angle;
        pidState.error = targetAngle - pidState.output;
        pidState.integral += pidState.error * dt;
        const derivative = (pidState.error - pidState.prevError) / dt;
        const control = state.params.pid.kp * pidState.error + state.params.pid.ki * pidState.integral + state.params.pid.kd * derivative;
        pidState.output = Math.max(Math.min(pidState.output + control, 1), -1);
        pidState.prevError = pidState.error;

        if(Math.abs(pidState.output - state.tele.user.angle) > 0.0001) {
          state.tele.user.angle = pidState.output;
          changed = true;
        }

        // I/K 控制油门：按住时增量变化
        if(state.keyInput.up && !state.keyInput.down) {
          state.tele.user.throttle = limitedThrottle(state.tele.user.throttle + state.params.accelRate * dt);
          changed = true;
        } else if(state.keyInput.down && !state.keyInput.up) {
          state.tele.user.throttle = limitedThrottle(state.tele.user.throttle - state.params.brakeRate * dt);
          changed = true;
        } else {
          // 松开 I/K 时自动减速至 0
          if(Math.abs(state.tele.user.throttle) > 0.001) {
            const signT = Math.sign(state.tele.user.throttle);
            const decel = state.params.accelRate * dt;
            const nextT = state.tele.user.throttle - signT * decel;
            state.tele.user.throttle = (signT > 0) ? Math.max(nextT, 0) : Math.min(nextT, 0);
            changed = true;
          }
        }

        // 若角度与油门均回到零且无按键，停止控制干预
        if(!anyKey && Math.abs(state.tele.user.angle) < 0.001 && Math.abs(state.tele.user.throttle) < 0.001) {
          arrowControlActive = false;
          pidState.output = 0;
          pidState.error = 0;
          pidState.prevError = 0;
          pidState.integral = 0;
          console.log('IKJL control deactivated');
        }

        if(changed) {
          console.log('IKJL sending:', {angle: state.tele.user.angle.toFixed(3), throttle: state.tele.user.throttle.toFixed(3)});
          postDrive(['angle','throttle']);
        }

        arrowControlLoop();
      }, 50);
    }

    var pidState = {
      error: 0,
      prevError: 0,
      integral: 0,
      output: 0,
    }

    this.load = function() {
      driveURL = '/drive'
      socket = new WebSocket('ws://' + location.host + '/wsDrive');

      loadPersistedParams();

      setBindings()

      bindParamInputs();
      bindParamManagementButtons();
      arrowControlLoop();

      joystick_element = document.getElementById('joystick_container');
      joystick_options = {
        zone: joystick_element,  // active zone
        mode: 'dynamic',
        size: 200,
        color: '#668AED',
        dynamicPage: true,
        follow: true,
      };

      var manager = nipplejs.create(joystick_options);
      bindNipple(manager)

      if(!!navigator.getGamepads){
        console.log("Device has gamepad support.")
        hasGamepad = true;
      }

      if (window.DeviceOrientationEvent) {
        window.addEventListener("deviceorientation", handleOrientation);
        console.log("Browser supports device orientation, setting control mode to tilt.");
        state.controlMode = 'tilt';
        deviceOrientationLoop();
      } else {
        console.log("Device Orientation not supported by browser, setting control mode to joystick.");
        state.controlMode = 'joystick';
      }
    };

    //
    // Update a state object with the given data.
    // This will only update existing fields in 
    // the state; it will not add new fields that
    // may exist in the data but not the state.
    //
    var updateState = function(state, data) {
        let changed = false;
        if(typeof data === 'object') {
            const keys = Object.keys(data)
            keys.forEach(key => {
                //
                // state must already have the key;
                // we are not adding new fields to the state,
                // we are only updating existing fields.
                //
                if(state.hasOwnProperty(key) && state[key] !== data[key]) {
                    if(typeof state[key] === 'object') {
                        // recursively update the state's object field
                        changed = updateState(state[key], data[key]) && changed;
                    } else {
                        state[key] = data[key];
                        changed = true;
                    }
                }
            });
        }
        return changed;
    }

    var setBindings = function() {
      //
      // when server sends a message with state changes
      // then update our local state and 
      // if there were any changes then redraw the UI.
      //
      socket.onmessage = function (event) {
        console.log(event.data);
        const data = JSON.parse(event.data);
        if(updateState(state, data)) {
            updateUI();
        }
      };

      $(document).keydown(function(e) {
          if(e.which == 32) { e.preventDefault(); toggleBrake() }  // 'space'  brake
          if(e.which == 82) { toggleRecording() }  // 'r'  toggle recording
          
          // IKJL 增量控制（替代方向键，带 PID + 回中 + 自动减速）
          if(e.which == 73) { state.keyInput.up = true; }      // 'I' 油门增加
          if(e.which == 75) { state.keyInput.down = true; }    // 'K' 刹车/倒车
          if(e.which == 74) { state.keyInput.left = true; }    // 'J' 左转
          if(e.which == 76) { state.keyInput.right = true; }   // 'L' 右转
          
          if(e.which == 65) { updateDriveMode('local') } // 'a' turn on local mode (full _A_uto)
          if(e.which == 85) { updateDriveMode('user') } // 'u' turn on manual mode (_U_user)
          if(e.which == 83) { updateDriveMode('local_angle') } // 's' turn on local mode (auto _S_teering)
          if(e.which == 77) { toggleDriveMode() } // 'm' toggle drive mode (_M_ode)
      });

      $(document).keyup(function(e) {
          // IKJL 松开时自动回中/减速
          if(e.which == 73) { state.keyInput.up = false; }
          if(e.which == 75) { state.keyInput.down = false; }
          if(e.which == 74) { state.keyInput.left = false; }
          if(e.which == 76) { state.keyInput.right = false; }
      });

      $('#mode_select').on('change', function () {
        updateDriveMode($(this).val());
      });

      $('#max_throttle_select').on('change', function () {
        state.maxThrottle = parseFloat($(this).val());
      });

      $('#throttle_mode_select').on('change', function () {
        state.throttleMode = $(this).val();
      });

      $('#record_button').click(function () {
        toggleRecording();
      });

      $('#brake_button').click(function() {
        toggleBrake();
      });

      $('input[type=radio][name=controlMode]').change(function() {
        if (this.value == 'joystick') {
          state.controlMode = "joystick";
          joystickLoopRunning = true;
          console.log('joystick mode');
          joystickLoop();
        } else {
          joystickLoopRunning = false;
        }

        if (deviceHasOrientation && this.value == 'tilt') {
          state.controlMode = "tilt";
          console.log('tilt mode')
        }

        if (hasGamepad && this.value == 'gamepad') {
          state.controlMode = "gamepad";
          console.log('gamepad mode')
          gamePadLoop();
        }
        updateUI();
      });

      // programmable buttons
      $('#button_bar > button').mousedown(function() {
        console.log(`${$(this).attr('id')} mousedown`);
        state.buttons[$(this).attr('id')] = true;
        postDrive(["buttons"]); // write it back to the server
      });
      $('#button_bar > button').mouseup(function() {
        console.log(`${$(this).attr('id')} mouseup`);
        state.buttons[$(this).attr('id')] = false;
        postDrive(["buttons"]); // write it back to the server
      });
    };

    var paramInputMap = [
      { id: 'pid_kp', path: ['pid','kp'], min: 0, max: 3, step: 0.05 },
      { id: 'pid_ki', path: ['pid','ki'], min: 0, max: 1, step: 0.01 },
      { id: 'pid_kd', path: ['pid','kd'], min: 0, max: 0.1, step: 0.001 },
      { id: 'recenter_rate', path: ['recenterRate'], min: 0, max: 2, step: 0.05 },
      { id: 'steer_rate', path: ['steerRate'], min: 0, max: 3, step: 0.05 },
      { id: 'accel_rate', path: ['accelRate'], min: 0, max: 3, step: 0.05 },
      { id: 'brake_rate', path: ['brakeRate'], min: 0, max: 3, step: 0.05 },
    ];

    var setDeepValue = function(root, path, val) {
      let cur = root;
      for(let i = 0; i < path.length - 1; i++) {
        cur = cur[path[i]];
      }
      cur[path[path.length - 1]] = val;
    }

    var getDeepValue = function(root, path) {
      let cur = root;
      path.forEach(p => { cur = cur[p]; });
      return cur;
    }

    var applyParamsToUI = function() {
      paramInputMap.forEach(cfg => {
        const el = document.getElementById(cfg.id);
        if(!el) { return; }
        el.min = cfg.min;
        el.max = cfg.max;
        el.step = cfg.step;
        el.value = getDeepValue(state.params, cfg.path);
        const label = document.querySelector(`[data-for="${cfg.id}"]`);
        if(label) { label.innerText = el.value; }
      });
    }

    var bindParamInputs = function() {
      applyParamsToUI();
      paramInputMap.forEach(cfg => {
        const el = document.getElementById(cfg.id);
        if(!el) { return; }
        el.addEventListener('input', function(evt) {
          const val = parseFloat(evt.target.value);
          setDeepValue(state.params, cfg.path, val);
          const label = document.querySelector(`[data-for="${cfg.id}"]`);
          if(label) { label.innerText = val; }
          savePersistedParams();
        });
      });
    }

    /**
     * 绑定参数管理按钮事件
     */
    var bindParamManagementButtons = function() {
      // 重置按钮
      const resetBtn = document.getElementById('reset_params_btn');
      if (resetBtn) {
        resetBtn.addEventListener('click', function() {
          if (confirm('确定要重置所有参数到默认值吗？')) {
            resetParams();
          }
        });
      }

      // 导出按钮
      const exportBtn = document.getElementById('export_params_btn');
      if (exportBtn) {
        exportBtn.addEventListener('click', function() {
          exportParams();
        });
      }

      // 导入文件选择
      const importFile = document.getElementById('import_params_file');
      if (importFile) {
        importFile.addEventListener('change', function(e) {
          if (e.target.files.length > 0) {
            importParams(e.target.files[0]);
            // 清空文件选择，允许重复导入同一文件
            e.target.value = '';
          }
        });
      }

      // 从服务器加载按钮
      const loadServerBtn = document.getElementById('load_server_params_btn');
      if (loadServerBtn) {
        loadServerBtn.addEventListener('click', function() {
          loadParamsFromServer();
        });
      }
    }

    function bindNipple(manager) {
      manager.on('start', function(evt, data) {
        state.tele.user.angle = 0
        state.tele.user.throttle = 0
        state.recording = true
        joystickLoopRunning=true;
        joystickLoop();

      }).on('end', function(evt, data) {
        joystickLoopRunning=false;
        brake()

      }).on('move', function(evt, data) {
        state.brakeOn = false;
        radian = data['angle']['radian']
        distance = data['distance']

        //console.log(data)
        state.tele.user.angle = Math.max(Math.min(Math.cos(radian)/70*distance, 1), -1)
        state.tele.user.throttle = limitedThrottle(Math.max(Math.min(Math.sin(radian)/70*distance , 1), -1))

        if (state.tele.user.throttle < .001) {
          state.tele.user.angle = 0
        }

      });
    }

    var updateUI = function() {
      applyParamsToUI();

      $("#throttleInput").val(state.tele.user.throttle);
      $("#angleInput").val(state.tele.user.angle);
      $('#mode_select').val(state.driveMode);

      var throttlePercent = Math.round(Math.abs(state.tele.user.throttle) * 100) + '%';
      var steeringPercent = Math.round(Math.abs(state.tele.user.angle) * 100) + '%';
      var throttleRounded = state.tele.user.throttle.toFixed(2)
      var steeringRounded = state.tele.user.angle.toFixed(2)

      $('#throttle_label').html(throttleRounded);
      $('#steering_label').html(steeringRounded);

      if(state.tele.user.throttle < 0) {
        $('#throttle-bar-backward').css('width', throttlePercent).html(throttleRounded)
        $('#throttle-bar-forward').css('width', '0%').html('')
      }
      else if (state.tele.user.throttle > 0) {
        $('#throttle-bar-backward').css('width', '0%').html('')
        $('#throttle-bar-forward').css('width', throttlePercent).html(throttleRounded)
      }
      else {
        $('#throttle-bar-forward').css('width', '0%').html('')
        $('#throttle-bar-backward').css('width', '0%').html('')
      }

      if(state.tele.user.angle < 0) {
        $('#angle-bar-backward').css('width', steeringPercent).html(steeringRounded)
        $('#angle-bar-forward').css('width', '0%').html('')
      }
      else if (state.tele.user.angle > 0) {
        $('#angle-bar-backward').css('width', '0%').html('')
        $('#angle-bar-forward').css('width', steeringPercent).html(steeringRounded)
      }
      else {
        $('#angle-bar-forward').css('width', '0%').html('')
        $('#angle-bar-backward').css('width', '0%').html('')
      }

      if (state.recording) {
        $('#record_button')
          .html('Stop Recording (r)')
          .removeClass('btn-info')
          .addClass('btn-warning').end()
      } else {
        $('#record_button')
          .html('Start Recording (r)')
          .removeClass('btn-warning')
          .addClass('btn-info').end()
      }

      if (state.brakeOn) {
        $('#brake_button')
          .html('Start Vehicle')
          .removeClass('btn-danger')
          .addClass('btn-success').end()
      } else {
        $('#brake_button')
          .html('Stop Vehicle')
          .removeClass('btn-success')
          .addClass('btn-danger').end()
      }

      if(deviceHasOrientation) {
        $('#tilt-toggle').removeAttr("disabled")
        $('#tilt').removeAttr("disabled")
      } else {
        $('#tilt-toggle').attr("disabled", "disabled");
        $('#tilt').prop("disabled", true);
      }

      if(hasGamepad) {
        $('#gamepad-toggle').removeAttr("disabled")
        $('#gamepad').removeAttr("disabled")
      } else {
        $('#gamepad-toggle').attr("disabled", "disabled");
        $('#gamepad').prop("disabled", true);
      }

      if (state.controlMode == "joystick") {
        $('#joystick_outer').show();
        $('#joystick-toggle').addClass("active");
        $('#joystick').attr("checked", "checked")
      } else {
        $('#joystick_outer').hide();
        $('#joystick-toggle').removeClass("active");
        $('#joystick').removeAttr("checked");
      }

      if (state.controlMode == "tilt") {
        $('#tilt-toggle').addClass("active");
        $('#tilt').attr("checked", "checked");
      } else {
        $('#tilt-toggle').removeClass("active");
        $('#tilt').removeAttr("checked")
      }

      //drawLine(state.tele.user.angle, state.tele.user.throttle)
    };

    const ALL_POST_FIELDS = ['angle', 'throttle', 'drive_mode', 'recording', 'buttons'];

    //
    // Set any changed properties to the server
    // via the websocket connection
    //
    var postDrive = function(fields=[]) {

        if(fields.length === 0) {
            fields = ALL_POST_FIELDS;
        }

        let data = {}
        fields.forEach(field => {
            switch (field) {
                case 'angle': data['angle'] = state.tele.user.angle; break;
                case 'throttle': data['throttle'] = state.tele.user.throttle; break;
                case 'drive_mode': data['drive_mode'] = state.driveMode; break;
                case 'recording': data['recording'] = state.recording; break;
                case 'buttons': data['buttons'] = state.buttons; break;
                default: console.log(`Unexpected post field: '${field}'`); break;
            }
        });
        if(data) {
            let json_data = JSON.stringify(data);
            if(socket && socket.readyState === WebSocket.OPEN) {
              console.log(`Posting ${json_data}`);
              socket.send(json_data)
              updateUI()
            } else {
              console.warn('WS not open, drop send', socket && socket.readyState);
            }
        }
    };

    var applyDeadzone = function(number, threshold){
       percentage = (Math.abs(number) - threshold) / (1 - threshold);

       if(percentage < 0)
          percentage = 0;

       return percentage * (number > 0 ? 1 : -1);
    }



    function gamePadLoop() {
      setTimeout(gamePadLoop,100);

      if (state.controlMode != "gamepad") {
        return;
      }

      var gamepads = navigator.getGamepads();

      for (var i = 0; i < gamepads.length; ++i)
        {
          var pad = gamepads[i];
          // some pads are NULL I think.. some aren't.. use one that isn't null
          if (pad && pad.timestamp!=0)
          {

            var joystickX = applyDeadzone(pad.axes[2], 0.05);

            var joystickY = applyDeadzone(pad.axes[1], 0.15);

            state.tele.user.angle = joystickX;
            state.tele.user.throttle = limitedThrottle((joystickY * -1));

            if (state.tele.user.throttle == 0 && state.tele.user.throttle == 0) {
              state.brakeOn = true;
            } else {
              state.brakeOn = false;
            }

            if (state.tele.user.throttle != 0) {
              state.recording = true;
            } else {
              state.recording = false;
            }

            postDrive()

          }
            // todo; simple demo of displaying pad.axes and pad.buttons
        }
      }


    // Send control updates to the server every .1 seconds.
    function joystickLoop () {
       setTimeout(function () {
            postDrive()

          if (joystickLoopRunning && state.controlMode == "joystick") {
             joystickLoop();
          }
       }, 100)
    }

    // Control throttle and steering with device orientation
    function handleOrientation(event) {

      var alpha = event.alpha;
      var beta = event.beta;
      var gamma = event.gamma;

      if (beta == null || gamma == null) {
        deviceHasOrientation = false;
        state.controlMode = "joystick";
        console.log("Invalid device orientation values, switched to joystick mode.")
      } else {
        deviceHasOrientation = true;
        console.log("device has valid orientation values")
      }

      updateUI();

      if(state.controlMode != "tilt" || !deviceHasOrientation || state.brakeOn){
        return;
      }

      if(!initialGamma && gamma) {
        initialGamma = gamma;
      }

      var newThrottle = gammaToThrottle(gamma);
      var newAngle = betaToSteering(beta, gamma);

      // prevent unexpected switch between full forward and full reverse
      // when device is parallel to ground
      if (state.tele.user.throttle > 0.9 && newThrottle <= 0) {
        newThrottle = 1.0
      }

      if (state.tele.user.throttle < -0.9 && newThrottle >= 0) {
        newThrottle = -1.0
      }

      state.tele.user.throttle = limitedThrottle(newThrottle);
      state.tele.user.angle = newAngle;
    }

    function deviceOrientationLoop () {
       setTimeout(function () {
          if(!state.brakeOn){
            postDrive()
          }

          if (state.controlMode == "tilt") {
            deviceOrientationLoop();
          }
       }, 100)
    }

    var throttleUp = function(){
      state.tele.user.throttle = limitedThrottle(Math.min(state.tele.user.throttle + .05, 1));
      postDrive()
    };

    var throttleDown = function(){
      state.tele.user.throttle = limitedThrottle(Math.max(state.tele.user.throttle - .05, -1));
      postDrive()
    };

    var angleLeft = function(){
      state.tele.user.angle = Math.max(state.tele.user.angle - .1, -1)
      postDrive()
    };

    var angleRight = function(){
      state.tele.user.angle = Math.min(state.tele.user.angle + .1, 1)
      postDrive()
    };

    var updateDriveMode = function(mode){
      state.driveMode = mode;
      postDrive(["drive_mode"])
    };

    var toggleDriveMode = function() {
      switch(state.driveMode) {
        case "user": {
            updateDriveMode("local_angle");
            break;
        }
        case "local_angle": {
            updateDriveMode("local");
            break;
        }
        default: {
            updateDriveMode("user");
            break;
        }
      }
    }

    var toggleRecording = function(){
      state.recording = !state.recording
      postDrive(['recording']);
    };

    var toggleBrake = function(){
      state.brakeOn = !state.brakeOn;
      initialGamma = null;

      if (state.brakeOn) {
        brake();
      }
    };

    var brake = function(i){
          console.log('post drive: ' + i)
          state.tele.user.angle = 0
          state.tele.user.throttle = 0
          state.recording = false
          state.driveMode = 'user';
          postDrive()

      i++
      if (i < 5) {
        setTimeout(function () {
          console.log('calling brake:' + i)
          brake(i);
        }, 500)
      };

      state.brakeOn = true;
      updateUI();
    };

    var limitedThrottle = function(newThrottle){
      var limitedThrottle = 0;

      if (newThrottle > 0) {
        limitedThrottle = Math.min(state.maxThrottle, newThrottle);
      }

      if (newThrottle < 0) {
        limitedThrottle = Math.max((state.maxThrottle * -1), newThrottle);
      }

      if (state.throttleMode == 'constant') {
        limitedThrottle = state.maxThrottle;
      }

      return limitedThrottle;
    }


    // var drawLine = function(angle, throttle) {
    //
    //   throttleConstant = 100
    //   throttle = throttle * throttleConstant
    //   angleSign = Math.sign(angle)
    //   angle = toRadians(Math.abs(angle*90))
    //
    //   var canvas = document.getElementById("angleView"),
    //   context = canvas.getContext('2d');
    //   context.clearRect(0, 0, canvas.width, canvas.height);
    //
    //   base={'x':canvas.width/2, 'y':canvas.height}
    //
    //   pointX = Math.sin(angle) * throttle * angleSign
    //   pointY = Math.cos(angle) * throttle
    //   xPoint = {'x': pointX + base.x, 'y': base.y - pointY}
    //
    //   context.beginPath();
    //   context.moveTo(base.x, base.y);
    //   context.lineTo(xPoint.x, xPoint.y);
    //   context.lineWidth = 5;
    //   context.strokeStyle = '#ff0000';
    //   context.stroke();
    //   context.closePath();
    //
    // };

    var betaToSteering = function(beta, gamma) {
      const deadZone = 5;
      var angle = 0.0;
      var outsideDeadZone = false;
      var controlDirection = (Math.sign(initialGamma) * -1)

      //max steering angle at device 35º tilt
      var fullLeft = -35.0;
      var fullRight = 35.0;

      //handle beta 90 to 180 discontinuous transition at gamma 90
      if (beta > 90) {
        beta = (beta - 180) * Math.sign(gamma * -1) * controlDirection
      } else if (beta < -90) {
        beta = (beta + 180) * Math.sign(gamma * -1) * controlDirection
      }

      // set the deadzone for neutral sterring
      if (Math.abs(beta) > 90) {
        outsideDeadZone = Math.abs(beta) < 180 - deadZone;
      }
      else {
        outsideDeadZone = Math.abs(beta) > deadZone;
      }

      if (outsideDeadZone && beta < -90.0) {
        angle = remap(beta, fullLeft, (-180.0 + deadZone), -1.0, 0.0);
      }
      else if (outsideDeadZone && beta > 90.0) {
        angle = remap(beta, (180.0 - deadZone), fullRight, 0.0, 1.0);
      }
      else if (outsideDeadZone && beta < 0.0) {
        angle = remap(beta, fullLeft, 0.0 - deadZone, -1.0, 0);
      }
      else if (outsideDeadZone && beta > 0.0) {
        angle = remap(beta, 0.0 + deadZone, fullRight, 0.0, 1.0);
      }

      // set full turn if abs(angle) > 1
      if (angle < -1) {
        angle = -1;
      } else if (angle > 1) {
        angle = 1;
      }

      return angle * controlDirection;
    };

    var gammaToThrottle = function(gamma) {
      var throttle = 0.0;
      var gamma180 = gamma + 90;
      var initialGamma180 = initialGamma + 90;
      var controlDirection = (Math.sign(initialGamma) * -1);

      // 10 degree deadzone around the initial position
      // 45 degrees of motion for forward and reverse
      var minForward = Math.min((initialGamma180 + (5 * controlDirection)), (initialGamma180 + (50 * controlDirection)));
      var maxForward = Math.max((initialGamma180 + (5 * controlDirection)), (initialGamma180 + (50 * controlDirection)));
      var minReverse = Math.min((initialGamma180 - (50 * controlDirection)), (initialGamma180 - (5 * controlDirection)));
      var maxReverse = Math.max((initialGamma180 - (50 * controlDirection)), (initialGamma180 - (5 * controlDirection)));

      //constrain control input ranges to 0..180 continuous range
      minForward = Math.max(minForward, 0);
      maxForward = Math.min(maxForward, 180);
      minReverse = Math.max(minReverse, 0);
      maxReverse = Math.min(maxReverse, 180);

      if(gamma180 > minForward && gamma180 < maxForward) {
        // gamma in forward range
        if (controlDirection == -1) {
          throttle = remap(gamma180, minForward, maxForward, 1.0, 0.0);
        } else {
          throttle = remap(gamma180, minForward, maxForward, 0.0, 1.0);
        }
      } else if (gamma180 > minReverse && gamma180 < maxReverse) {
        // gamma in reverse range
        if (controlDirection == -1) {
          throttle = remap(gamma180, minReverse, maxReverse, 0.0, -1.0);
        } else  {
          throttle = remap(gamma180, minReverse, maxReverse, -1.0, 0.0);
        }
      }

      return throttle;
    };

}();


function toRadians (angle) {
  return angle * (Math.PI / 180);
}

function remap( x, oMin, oMax, nMin, nMax ){
  //range check
  if (oMin == oMax){
      console.log("Warning: Zero input range");
      return None;
  };

  if (nMin == nMax){
      console.log("Warning: Zero output range");
      return None
  }

  //check reversed input range
  var reverseInput = false;
  oldMin = Math.min( oMin, oMax );
  oldMax = Math.max( oMin, oMax );
  if (oldMin != oMin){
      reverseInput = true;
  }

  //check reversed output range
  var reverseOutput = false;
  newMin = Math.min( nMin, nMax )
  newMax = Math.max( nMin, nMax )
  if (newMin != nMin){
      reverseOutput = true;
  };

  var portion = (x-oldMin)*(newMax-newMin)/(oldMax-oldMin)
  if (reverseInput){
      portion = (oldMax-x)*(newMax-newMin)/(oldMax-oldMin);
  };

  var result = portion + newMin
  if (reverseOutput){
      result = newMax - portion;
  }

return result;
}

