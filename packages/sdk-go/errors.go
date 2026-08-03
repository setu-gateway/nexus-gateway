package setu

import "fmt"

// APIError is returned when the gateway responds with a non-2xx status.
type APIError struct {
	StatusCode int
	Body       string
}

func (e *APIError) Error() string {
	return fmt.Sprintf("setu gateway request failed (%d): %s", e.StatusCode, e.Body)
}

// ConnectionError is returned when the gateway can't be reached at all.
type ConnectionError struct {
	Err error
}

func (e *ConnectionError) Error() string {
	return fmt.Sprintf("could not reach setu gateway: %v", e.Err)
}

func (e *ConnectionError) Unwrap() error {
	return e.Err
}
