

const category = document.querySelector("#category")

category.addEventListener("change", function(){
    

    fetch("/select-category", {
        method: "POST",

        headers: {
            "Content-Type": "application/json"
        },

        body: JSON.stringify({
            category_id: category.value
        })
    })
    .then(function(response) {
        return response.json();
    }) 

    .then(function(data) {
        if(data.success){
            console.log("Category chosen successfully")
        }
        else{
            console.log("Could not choose category")
        }
    });
})

const timer = document.querySelector("#timer")
const start = document.querySelector("#start")
const stop = document.querySelector("#stop")
const continued = document.querySelector("#continued")
const deleted = document.querySelector("#delete")
const finish = document.querySelector("#finish")

stop.hidden = true;
continued.hidden = true;
deleted.hidden = true;
finish.hidden = true;

let startTime = null;
let timerInterval = null;
let elapsedBeforePaused = 0;

start.addEventListener("click", function(){
    startTime = Date.now()
    timerInterval = setInterval(updateTimer, 1000);
    start.hidden = true;
    stop.hidden = false;
})

function updateTimer(){
    let now = Date.now()
    let elapsed = elapsedBeforePaused + (now - startTime);
    let total_seconds = Math.floor(elapsed/1000);
    timer.textContent = formatTime(total_seconds);
}

function formatTime(total_seconds){
    let hours = Math.trunc(total_seconds/3600);
    let minutes = Math.trunc((total_seconds % 3600)/60)
    let seconds = total_seconds % 60
    return `${String(hours).padStart(2, 0)}:${String(minutes).padStart(2, 0)}:${String(seconds).padStart(2, 0)}`
    
}

stop.addEventListener("click", function(){
    clearInterval(timerInterval);
    elapsedBeforePaused += Date.now() - startTime;
    stop.hidden = true;
    continued.hidden = false;
    deleted.hidden = false;
    finish.hidden = false;
});

continued.addEventListener("click", function(){
    startTime = Date.now()
    timerInterval = setInterval(updateTimer, 1000);
    continued.hidden = true;
    stop.hidden = false;
    deleted.hidden = true;
    finish.hidden = true;
});

deleted.addEventListener("click", function(){
    timer.textContent = "00:00:00";
    elapsedBeforePaused = 0;
    startTime = null;
    deleted.hidden = true;
    continued.hidden = true;
    start.hidden = false;
    finish.hidden = true;
})

finish.addEventListener("click", function(){
    let finalElapsedTime = Math.floor(elapsedBeforePaused/1000);
    console.log(finalElapsedTime);
    
    fetch("/finish", {
        method: "POST",

        headers: {
            "Content-Type": "application/json"
        },

        body: JSON.stringify({
            duration: finalElapsedTime    
        })
    })
    .then(function(response) {
    return response.json();
    }) 

    .then(function(data) {
        if(data.success){
            window.location.href = "/finish"
        }
        else{
            console.log("Could not choose category")
        }
    });
})

