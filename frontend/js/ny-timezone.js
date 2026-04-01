/* US Eastern (America/New_York) for trading ops — independent of browser/local machine TZ. */
window.REC_IO_NY_TZ = "America/New_York";

window.formatRecNyLocaleString = function (value) {
    if (value == null || value === "") return "Unknown";
    try {
        return new Date(value).toLocaleString("en-US", { timeZone: window.REC_IO_NY_TZ });
    } catch (e) {
        return String(value);
    }
};

window.formatRecNyTimeString = function (value, extraOptions) {
    var o = { timeZone: window.REC_IO_NY_TZ, hour: "2-digit", minute: "2-digit", second: "2-digit" };
    if (extraOptions && typeof extraOptions === "object") {
        for (var k in extraOptions) {
            if (Object.prototype.hasOwnProperty.call(extraOptions, k)) o[k] = extraOptions[k];
        }
    }
    return new Date(value).toLocaleTimeString("en-US", o);
};

window.formatRecNyDateString = function (value, extraOptions) {
    var o = { timeZone: window.REC_IO_NY_TZ };
    if (extraOptions && typeof extraOptions === "object") {
        for (var k2 in extraOptions) {
            if (Object.prototype.hasOwnProperty.call(extraOptions, k2)) o[k2] = extraOptions[k2];
        }
    }
    return new Date(value).toLocaleDateString("en-US", o);
};
