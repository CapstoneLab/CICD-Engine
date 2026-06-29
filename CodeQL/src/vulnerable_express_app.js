const express = require("express");
const fs = require("fs");
const childProcess = require("child_process");

const app = express();

app.get("/search", (req, res) => {
  const term = req.query.q || "";
  const html = "<h1>Search</h1><p>" + term + "</p>";
  res.send(html);
});

app.get("/file", (req, res) => {
  const filename = req.query.name || "README.md";
  const body = fs.readFileSync("uploads/" + filename, "utf8");
  res.type("text/plain").send(body);
});

app.get("/run", (req, res) => {
  const command = "echo " + (req.query.message || "hello");
  childProcess.exec(command, (error, stdout, stderr) => {
    if (error) {
      res.status(500).send(stderr);
      return;
    }
    res.type("text/plain").send(stdout);
  });
});

app.get("/eval", (req, res) => {
  const expression = req.query.expression || "1 + 1";
  res.send(String(eval(expression)));
});

app.listen(3000, () => {
  console.log("vulnerable example listening on port 3000");
});
