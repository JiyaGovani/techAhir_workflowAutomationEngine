const builder = document.getElementById("step-builder");
const stepsJson = document.getElementById("steps");
const form = document.getElementById("workflow-form");

function createField(labelText, value, className) {
    const label = document.createElement("label");
    label.textContent = labelText;
    const input = document.createElement("input");
    input.type = "text";
    input.className = className;
    input.value = value == null ? "" : value;
    label.appendChild(input);
    return label;
}

function addStep(step) {
    step = step || {type: "TASK", task: "record_order_created", config: {order_id: ""}};
    const card = document.createElement("div");
    card.className = "step-card";

    const typeLabel = document.createElement("label");
    typeLabel.textContent = "Step type";
    const typeSelect = document.createElement("select");
    typeSelect.className = "step-type";
    ["TASK", "WAIT", "MESSAGE", "CONDITION"].forEach((type) => {
        const option = document.createElement("option");
        option.value = type;
        option.textContent = type;
        option.selected = type === step.type;
        typeSelect.appendChild(option);
    });
    typeLabel.appendChild(typeSelect);
    card.appendChild(typeLabel);

    const fields = document.createElement("div");
    fields.className = "step-fields";
    card.appendChild(fields);

    function renderFields() {
        fields.replaceChildren();
        const type = typeSelect.value;

        if (type === "TASK") {
            fields.appendChild(createField("Task name", step.task || "record_order_created", "task-name"));
            fields.appendChild(createField("Task config JSON", JSON.stringify(step.config || {}), "task-config"));
        } else if (type === "WAIT") {
            fields.appendChild(createField("Seconds", step.seconds || 30, "wait-seconds"));
        } else if (type === "MESSAGE") {
            fields.appendChild(createField("Recipient", step.recipient || "", "message-recipient"));
            fields.appendChild(createField("Message", step.content || "", "message-content"));
        } else {
            fields.appendChild(createField("Field", step.field || "order_value", "condition-field"));

            const operatorLabel = document.createElement("label");
            operatorLabel.textContent = "Operator";
            const operator = document.createElement("select");
            operator.className = "condition-operator";
            ["gt", "gte", "lt", "lte", "eq", "ne", "in"].forEach((value) => {
                const option = document.createElement("option");
                option.value = value;
                option.textContent = value;
                option.selected = value === (step.operator || "gt");
                operator.appendChild(option);
            });
            operatorLabel.appendChild(operator);
            fields.appendChild(operatorLabel);

            fields.appendChild(createField("Value", JSON.stringify(step.value ?? 500), "condition-value"));
            fields.appendChild(createField("True next index", step.true_next ?? "", "true-next"));
            fields.appendChild(createField("False next index", step.false_next ?? "", "false-next"));
        }
    }

    typeSelect.addEventListener("change", renderFields);
    renderFields();

    const actions = document.createElement("div");
    actions.className = "step-actions";

    const up = document.createElement("button");
    up.type = "button";
    up.textContent = "Move up";
    up.addEventListener("click", () => {
        if (card.previousElementSibling) {
            builder.insertBefore(card, card.previousElementSibling);
        }
    });

    const down = document.createElement("button");
    down.type = "button";
    down.textContent = "Move down";
    down.addEventListener("click", () => {
        if (card.nextElementSibling) {
            builder.insertBefore(card.nextElementSibling, card);
        }
    });

    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "Remove";
    remove.addEventListener("click", () => card.remove());

    actions.append(up, down, remove);
    card.appendChild(actions);
    builder.appendChild(card);
}

function collectSteps() {
    return Array.from(builder.querySelectorAll(".step-card")).map((card) => {
        const type = card.querySelector(".step-type").value;
        if (type === "TASK") {
            return {
                type,
                task: card.querySelector(".task-name").value.trim(),
                config: JSON.parse(card.querySelector(".task-config").value || "{}"),
            };
        }
        if (type === "WAIT") {
            return {type, seconds: Number(card.querySelector(".wait-seconds").value)};
        }
        if (type === "MESSAGE") {
            return {
                type,
                recipient: card.querySelector(".message-recipient").value.trim(),
                content: card.querySelector(".message-content").value,
            };
        }

        const trueNext = card.querySelector(".true-next").value;
        const falseNext = card.querySelector(".false-next").value;
        return {
            type,
            field: card.querySelector(".condition-field").value.trim(),
            operator: card.querySelector(".condition-operator").value,
            value: JSON.parse(card.querySelector(".condition-value").value),
            true_next: trueNext === "" ? null : Number(trueNext),
            false_next: falseNext === "" ? null : Number(falseNext),
        };
    });
}

document.getElementById("add-step").addEventListener("click", () => addStep());
form.addEventListener("submit", (event) => {
    try {
        stepsJson.value = JSON.stringify(collectSteps(), null, 2);
    } catch (error) {
        event.preventDefault();
        alert("Invalid step configuration: " + error.message);
    }
});

try {
    const initialSteps = JSON.parse(stepsJson.value);
    builder.replaceChildren();
    initialSteps.forEach(addStep);
} catch (error) {
    addStep();
}
