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
        // 方向键状态
        'keyInput': {
            'left': false,
            'right': false,
            'up': false,
            'down': false,
        }
    }

    const PARAM_STORAGE_KEY = 'dkc_drive_params';

    var joystick_options = {}
    var joystickLoopRunning=false;

    var hasGamepad = false;

    var deviceHasOrientation=false;
    var initialGamma;

    var vehicle_id = ""
    var driveURL = ""
    var socket

    // ---------- 参数持久化 ----------
    var loadPersistedParams = function() {
      try {
        const raw = localStorage.getItem(PARAM_STORAGE_KEY);
        if(!raw) { return; }
        const data = JSON.parse(raw);
        if(data && data.params) {
          updateState(state.params, data.params);
        }
      } catch (err) {
        console.warn('Failed to load params', err);
      }
    }

    var savePersistedParams = function() {
      try {
        localStorage.setItem(PARAM_STORAGE_KEY, JSON.stringify({ params: state.params }));
      } catch (err) {
        console.warn('Failed to save params', err);
      }
    }

    // ---------- 键盘方向控制循环 ----------
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
          console.log('Arrow keys active:', state.keyInput);
        }
        if(!arrowControlActive) {
          arrowControlLoop();
          return;
        }

        // 目标角速度积分（左右键）
        if(state.keyInput.left && !state.keyInput.right) {
          state.tele.user.angle = Math.max(state.tele.user.angle - state.params.steerRate * dt, -1);
          changed = true;
        } else if(state.keyInput.right && !state.keyInput.left) {
          state.tele.user.angle = Math.min(state.tele.user.angle + state.params.steerRate * dt, 1);
          changed = true;
        } else {
          // 回中
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

        // 油门增量与松手回零
        if(state.keyInput.up && !state.keyInput.down) {
          state.tele.user.throttle = limitedThrottle(state.tele.user.throttle + state.params.accelRate * dt);
          changed = true;
        } else if(state.keyInput.down && !state.keyInput.up) {
          state.tele.user.throttle = limitedThrottle(state.tele.user.throttle - state.params.brakeRate * dt);
          changed = true;
        } else {
          // 松手自动减速
          if(Math.abs(state.tele.user.throttle) > 0.001) {
            const signT = Math.sign(state.tele.user.throttle);
            const decel = state.params.accelRate * dt;
            const nextT = state.tele.user.throttle - signT * decel;
            state.tele.user.throttle = (signT > 0) ? Math.max(nextT, 0) : Math.min(nextT, 0);
            changed = true;
          }
        }

        // 若角度与油门均回到零且无按键，停止箭控干预
        if(!anyKey && Math.abs(state.tele.user.angle) < 0.001 && Math.abs(state.tele.user.throttle) < 0.001) {
          arrowControlActive = false;
          pidState.output = 0;
          pidState.error = 0;
          pidState.prevError = 0;
          pidState.integral = 0;
          console.log('Arrow control deactivated');
        }

        if(changed) {
          console.log('Sending control:', {angle: state.tele.user.angle.toFixed(3), throttle: state.tele.user.throttle.toFixed(3)});
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

      // 使用原生事件捕获阶段拦截方向键，优先级最高
      window.addEventListener('keydown', function(e) {
          const arrowKeys = [37, 38, 39, 40]; // left, up, right, down
          if(arrowKeys.includes(e.keyCode || e.which)) {
            e.preventDefault();
            e.stopPropagation();
            console.log('Arrow key down:', e.keyCode || e.which);
            
            switch(e.keyCode || e.which) {
              case 37: state.keyInput.left = true; break;   // left
              case 38: state.keyInput.up = true; break;     // up
              case 39: state.keyInput.right = true; break;  // right
              case 40: state.keyInput.down = true; break;   // down
            }
            return false;
          }
      }, true); // 使用捕获阶段

      window.addEventListener('keyup', function(e) {
          const arrowKeys = [37, 38, 39, 40];
          if(arrowKeys.includes(e.keyCode || e.which)) {
            e.preventDefault();
            e.stopPropagation();
            console.log('Arrow key up:', e.keyCode || e.which);
            
            switch(e.keyCode || e.which) {
              case 37: state.keyInput.left = false; break;
              case 38: state.keyInput.up = false; break;
              case 39: state.keyInput.right = false; break;
              case 40: state.keyInput.down = false; break;
            }
            return false;
          }
      }, true); // 使用捕获阶段

      $(document).keydown(function(e) {
          if(e.which == 32) { e.preventDefault(); toggleBrake() }  // 'space'  brake
          if(e.which == 82) { toggleRecording() }  // 'r'  toggle recording
          if(e.which == 73) { throttleUp() }  // 'i'  throttle up
          if(e.which == 75) { throttleDown() } // 'k'  slow down
          if(e.which == 74) { angleLeft() } // 'j' turn left
          if(e.which == 76) { angleRight() } // 'l' turn right
          if(e.which == 65) { updateDriveMode('local') } // 'a' turn on local mode (full _A_uto)
          if(e.which == 85) { updateDriveMode('user') } // 'u' turn on manual mode (_U_user)
          if(e.which == 83) { updateDriveMode('local_angle') } // 's' turn on local mode (auto _S_teering)
          if(e.which == 77) { toggleDriveMode() } // 'm' toggle drive mode (_M_ode)
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
      { id: 'pid_kd', path: ['pid','kd'], min: 0, max: 2, step: 0.05 },
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

